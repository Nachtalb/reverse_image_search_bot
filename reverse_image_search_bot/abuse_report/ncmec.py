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
        )
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

    return PersonOrUserReported(
        esp_identifier=str(reported_user["user_id"]) if reported_user.get("user_id") else None,
        esp_service=settings.NCMEC_ESP_NAME or "Reverse Image Search Bot",
        screen_name=(f"@{reported_user['username']}" if reported_user.get("username") else None),
        display_name=display,
        profile_url=profile_urls,
        group_identifier="; ".join(group_bits) or None,
    )


def build_report(
    *,
    incident_urls: list[str],
    reported_user: dict | None = None,
    source_chats: list[dict] | None = None,
) -> Report:
    """Build the report envelope. One report per user round."""
    return Report(
        incident_summary=IncidentSummary(
            incident_type=IncidentType.CHILD_PORNOGRAPHY,
            incident_date_time=datetime.now(UTC),
        ),
        internet_details=[
            InternetDetails(web_page_incident=WebPageIncident(url=incident_urls or ["https://ris.naa.gg/"]))
        ],
        reporter=_reporter(),
        person_or_user_reported=build_reported_subject(reported_user, source_chats),
    )


async def submit_report(
    selected_files: list[dict],
    *,
    incident_urls: list[str],
    reported_user: dict | None = None,
    source_chats: list[dict] | None = None,
) -> tuple[int, list[str]]:
    """Open a report and upload every selected file with its classification.

    ``selected_files`` is a list of dicts with keys: ``plaintext`` (decrypted
    bytes), ``filename``, ``classification`` (A1/A2/B1/B2 or None), ``uploaded_at``
    (unix ts or None). ``reported_user`` is the uploader profile and
    ``source_chats`` the group/channel chats their files came through — both are
    stamped onto the report as the reported subject. Returns
    ``(ncmec_report_id, [file_id, ...])``.

    Does NOT finish the report — the admin does a final review, then calls
    :func:`finish_report` or :func:`retract_report`.
    """
    async with _client() as client:
        await client.status()  # verify connectivity + auth up front
        opened = await client.submit(
            build_report(incident_urls=incident_urls, reported_user=reported_user, source_chats=source_chats)
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

            details = FileDetails(
                report_id=report_id,
                file_id=file_id,
                original_file_name=f["filename"],
                file_relevance=FileRelevance.REPORTED,
                file_viewed_by_esp=True,
                industry_classification=_CLASSIFICATION.get(f.get("classification") or ""),
                original_file_hash=file_hashes(data),
            )
            await client.file_info(details)

        return report_id, file_ids


async def finish_report(report_id: int) -> int:
    """Finish (file) the report with NCMEC. Irreversible."""
    async with _client() as client:
        done = await client.finish(report_id)
        return done.report_id or report_id


async def retract_report(report_id: int) -> None:
    """Retract an unfinished report."""
    async with _client() as client:
        await client.retract(report_id)
