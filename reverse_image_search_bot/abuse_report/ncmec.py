"""NCMEC CyberTipline submission for a prepared abuse report.

Wraps the ``ncmec-cybertip`` client's lifecycle: submit -> upload each selected
file -> file_info (with A1/A2/B1/B2 classification + hashes) -> finish / retract.

The report data comes from the abuse DB (decrypted server-side from the blobs
using P1, which the admin supplies at submit time — it is never stored).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ncmec_cybertip import (
    PRODUCTION_URL,
    TESTING_URL,
    ChatImIncident,
    CyberTiplineClient,
    Email,
    FileDetails,
    FileRelevance,
    IncidentSummary,
    IncidentType,
    IndustryClassification,
    InternetDetails,
    Person,
    PersonOrUserReported,
    Report,
    Reporter,
    WebPageIncident,
    file_hashes,
)

from reverse_image_search_bot import settings

logger = logging.getLogger("abuse.ncmec")

# "NR" (Not Rated) is intentionally absent: a file may be reported without an
# industry classification (the field is optional), so _CLASSIFICATION.get("NR")
# returns None and industry_classification is omitted from the FileDetails.
_CLASSIFICATION = {
    "A1": IndustryClassification.A1,
    "A2": IndustryClassification.A2,
    "B1": IndustryClassification.B1,
    "B2": IndustryClassification.B2,
}


class NcmecNotConfigured(RuntimeError):
    pass


def _client() -> CyberTiplineClient:
    if not (settings.NCMEC_USERNAME and settings.NCMEC_PASSWORD):
        raise NcmecNotConfigured("NCMEC_USERNAME / NCMEC_PASSWORD not set")
    return CyberTiplineClient(
        username=settings.NCMEC_USERNAME,
        password=settings.NCMEC_PASSWORD,
        base_url=TESTING_URL if settings.NCMEC_TESTING else PRODUCTION_URL,
    )


def _reporter() -> Reporter:
    return Reporter(
        reporting_person=Person(
            first_name=settings.NCMEC_REPORTER_FIRST_NAME or None,
            last_name=settings.NCMEC_REPORTER_LAST_NAME or None,
            email=[Email(value=settings.NCMEC_REPORTER_EMAIL)] if settings.NCMEC_REPORTER_EMAIL else [],
        ),
        terms_of_service=settings.NCMEC_TERMS_OF_SERVICE or None,
    )


def build_reported_subject(
    reported_user: dict | None,
    source_chats: list[dict] | None,
) -> PersonOrUserReported | None:
    """Build the reported suspect (the uploader) + any group/channel context.

    The uploader is the reported person: their Telegram id becomes the ESP
    identifier, username/name the screen/display name. Groups and channels the
    files were uploaded through are attached as ``groupIdentifier`` /
    ``associatedAccount`` so NCMEC sees the full source context.
    """
    if not reported_user and not source_chats:
        return None

    reported_user = reported_user or {}
    display: list[str] = []
    full = " ".join(x for x in (reported_user.get("first_name"), reported_user.get("last_name")) if x).strip()
    if full:
        display.append(full)
    profile_urls: list[str] = []
    if reported_user.get("username"):
        profile_urls.append(f"https://t.me/{reported_user['username']}")

    # Group/channel context → groupIdentifier text + associatedAccount rows.
    group_bits: list[str] = []
    for c in source_chats or []:
        label = c.get("title") or (f"@{c['username']}" if c.get("username") else str(c.get("chat_id")))
        group_bits.append(f"{c.get('chat_type', 'chat')}: {label} (id {c.get('chat_id')})")

    # NCMEC has no dedicated language field, so the uploader's Telegram UI
    # language (IETF tag reported by the client) goes into additionalInfo.
    info_bits: list[str] = []
    lang = reported_user.get("language_code")
    if lang:
        info_bits.append(f"Telegram UI language (IETF tag): {lang}")

    return PersonOrUserReported(
        esp_identifier=str(reported_user["user_id"]) if reported_user.get("user_id") else None,
        esp_service=settings.NCMEC_ESP_NAME or "Reverse Image Search Bot",
        screen_name=(f"@{reported_user['username']}" if reported_user.get("username") else None),
        display_name=display,
        profile_url=profile_urls,
        profile_bio=reported_user.get("bio") or None,
        group_identifier="; ".join(group_bits) or None,
        additional_info="\n".join(info_bits) or None,
    )


def build_report(
    *,
    incident_urls: list[str],
    reported_user: dict | None = None,
    source_chats: list[dict] | None = None,
    incident_date: datetime | None = None,
    chat_room_name: str | None = None,
) -> Report:
    """Build the report envelope. One report per user round.

    ``incident_date`` is the time of the first reported media item's upload (must
    be in the past); falls back to now only if unknown. ``chat_room_name`` is a
    short label for where the media was sent (the bot DM, or a group/channel).
    """
    internet_details = [
        InternetDetails(web_page_incident=WebPageIncident(url=incident_urls or ["https://ris.naa.gg/"]))
    ]
    # The media was delivered to the bot over Telegram — record that as the chat
    # incident alongside the web page (re-hosted copy) details.
    internet_details.append(
        InternetDetails(
            chat_im_incident=ChatImIncident(
                chat_client="Telegram",
                chat_room_name=chat_room_name or None,
            )
        )
    )
    return Report(
        incident_summary=IncidentSummary(
            incident_type=IncidentType.CHILD_PORNOGRAPHY,
            incident_date_time=incident_date or datetime.now(UTC),
            incident_date_time_description="Time of the first reported media item uploaded to the bot.",
        ),
        internet_details=internet_details,
        reporter=_reporter(),
        person_or_user_reported=build_reported_subject(reported_user, source_chats),
    )


def build_file_details(report_id: int, file_id: str, f: dict, data: bytes) -> FileDetails:
    """Build the per-file NCMEC FileDetails for one selected file.

    Shared by the live submit path AND the review preview, so what the admin
    sees is byte-for-byte what gets sent. The live submit passes the real
    NCMEC-assigned ``report_id``/``file_id``; the preview passes placeholders
    (0 / a marker string) and strips them from the dumped output.

    ``uploaded_to_esp_timestamp`` is this file's real upload time (must be in the
    past); omitted if unknown — never faked to ``now``. A user caption, if the
    media was sent with one, goes into ``additional_info``.
    """
    caption = (f.get("caption") or "").strip()
    additional_info = [f"User caption: {caption}"] if caption else []
    return FileDetails(
        report_id=report_id,
        file_id=file_id,
        original_file_name=f["filename"],
        uploaded_to_esp_timestamp=f.get("upload_time") or None,
        location_of_file=f.get("location") or None,
        publicly_available=True if f.get("location") else None,
        file_relevance=FileRelevance.REPORTED,
        file_viewed_by_esp=True,
        industry_classification=_CLASSIFICATION.get(f.get("classification") or ""),
        original_file_hash=file_hashes(data),
        additional_info=additional_info,
    )


def preview_payload(
    files: list[dict],
    *,
    incident_urls: list[str],
    reported_user: dict | None = None,
    source_chats: list[dict] | None = None,
    incident_date: datetime | None = None,
    chat_room_name: str | None = None,
) -> dict:
    """Build the EXACT objects that submit_and_finish would send, as plain dicts.

    Uses the same ``build_report`` / ``build_file_details`` builders as the live
    submit, so the review dialog shows precisely what NCMEC receives — nothing is
    hand-mirrored. No network calls; nothing is filed.
    """
    report = build_report(
        incident_urls=incident_urls,
        reported_user=reported_user,
        source_chats=source_chats,
        incident_date=incident_date,
        chat_room_name=chat_room_name,
    )
    # report_id / file_id are assigned by NCMEC at submit time; the model requires
    # them, so use clearly-marked placeholders for the preview and strip them from
    # the dumped output (they are NOT part of what the admin is reviewing).
    file_details = [build_file_details(0, "(assigned on submit)", f, f["plaintext"]) for f in files]
    file_dumps = []
    for fd in file_details:
        d = fd.model_dump(mode="json", exclude_none=True, by_alias=True)
        d.pop("report_id", None)
        d.pop("file_id", None)
        file_dumps.append(d)
    return {
        "report": report.model_dump(mode="json", exclude_none=True, by_alias=True),
        "files": file_dumps,
    }


async def submit_and_finish(
    selected_files: list[dict],
    *,
    incident_urls: list[str],
    reported_user: dict | None = None,
    source_chats: list[dict] | None = None,
    incident_date: datetime | None = None,
    chat_room_name: str | None = None,
) -> tuple[int, list[str]]:
    """Open, populate, AND finish a report in one shot (irreversible).

    The report console double-checks everything client-side before this is
    called, so there is no separate review/finish step: submit -> upload each
    file -> file_info -> finish, all under one client session. Returns
    ``(ncmec_report_id, [file_id, ...])``.
    """
    async with _client() as client:
        await client.status()  # verify connectivity + auth up front
        opened = await client.submit(
            build_report(
                incident_urls=incident_urls,
                reported_user=reported_user,
                source_chats=source_chats,
                incident_date=incident_date,
                chat_room_name=chat_room_name,
            )
        )
        report_id = opened.report_id
        if report_id is None:
            raise RuntimeError(f"NCMEC submit returned no report_id: {opened!r}")

        file_ids: list[str] = []
        for f in selected_files:
            data: bytes = f["plaintext"]
            up = await client.upload(report_id, data, filename=f["filename"])
            file_id = up.file_id
            if file_id is None:
                raise RuntimeError(f"NCMEC upload returned no file_id for {f['filename']}")
            file_ids.append(file_id)

            details = build_file_details(report_id, file_id, f, data)
            await client.file_info(details)

        await client.finish(report_id)
        return report_id, file_ids
