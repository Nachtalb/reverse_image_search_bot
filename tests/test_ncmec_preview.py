"""Tests for the NCMEC review-preview payload builder.

The review dialog must show EXACTLY what the live submit sends, so
``preview_payload`` reuses the same ``build_report`` / ``build_file_details``
builders as ``submit_and_finish``. These tests lock that guarantee: the preview's
per-file FileDetails must equal the submit-path FileDetails (modulo the
report_id/file_id assigned by NCMEC at submit time), and NR must omit the
industry classification.
"""

from __future__ import annotations

from reverse_image_search_bot.abuse_report import ncmec


def _files():
    return [
        {
            "kind": "frame",
            "blob_id": 1,
            "plaintext": b"\xff\xd8\xff frame-bytes",
            "filename": "cat.jpg",
            "location": "https://ris.naa.gg/f/AQ.jpg",
            "classification": "A1",
        },
        {
            "kind": "video",
            "blob_id": 1,
            "plaintext": b"\x00\x00\x00 ftypmp42 video-bytes",
            "filename": "cat.mp4",
            "classification": "A1",
        },
        {
            "kind": "frame",
            "blob_id": 2,
            "plaintext": b"\xff\xd8\xff nr-image",
            "filename": "AQ2.jpg",
            "location": "https://ris.naa.gg/f/AQ2.jpg",
            "classification": "NR",
        },
    ]


def test_preview_matches_submit_file_details():
    """Preview FileDetails == submit FileDetails, ignoring report_id/file_id."""
    files = _files()
    preview = ncmec.preview_payload(
        files,
        incident_urls=["https://ris.naa.gg/f/AQ.jpg"],
        reported_user={"user_id": 42, "username": "bad", "first_name": "B", "last_name": "G"},
        source_chats=None,
    )
    for f, dumped in zip(files, preview["files"], strict=True):
        # Build the same object the submit path would (with real placeholder ids)
        # and dump it the same way, then strip the ids the preview strips.
        submit_fd = ncmec.build_file_details(999, "FILEID", f, f["plaintext"])
        d = submit_fd.model_dump(mode="json", exclude_none=True, by_alias=True)
        d.pop("report_id", None)
        d.pop("file_id", None)
        assert dumped == d


def test_preview_video_and_frame_both_present():
    """A video upload contributes BOTH a frame and a video file to the payload."""
    files = _files()
    preview = ncmec.preview_payload(files, incident_urls=["https://ris.naa.gg/f/AQ.jpg"])
    names = [fd["original_file_name"] for fd in preview["files"]]
    assert "cat.jpg" in names  # extracted frame
    assert "cat.mp4" in names  # source video
    assert len(preview["files"]) == 3


def test_preview_nr_omits_industry_classification():
    """NR-classified file carries no industry_classification; A1 does."""
    files = _files()
    preview = ncmec.preview_payload(files, incident_urls=["https://ris.naa.gg/f/AQ.jpg"])
    by_name = {fd["original_file_name"]: fd for fd in preview["files"]}
    assert by_name["cat.jpg"]["industry_classification"] == "A1"
    assert "industry_classification" not in by_name["AQ2.jpg"]  # NR -> omitted


def test_preview_hashes_present():
    """Every file in the preview carries MD5/SHA1/SHA256 hashes (what NCMEC gets)."""
    files = _files()
    preview = ncmec.preview_payload(files, incident_urls=["https://ris.naa.gg/f/AQ.jpg"])
    for fd in preview["files"]:
        types = {h["hash_type"] for h in fd["original_file_hash"]}
        assert {"MD5", "SHA1", "SHA256"} <= types


def test_preview_no_reported_when_no_user():
    """No reported person/account when there's no uploader and no chats."""
    files = _files()
    preview = ncmec.preview_payload(files, incident_urls=["https://ris.naa.gg/f/AQ.jpg"])
    assert preview["report"].get("person_or_user_reported") is None


def test_preview_incident_date_and_description():
    """incidentDateTime uses the passed date; description is always set."""
    from datetime import UTC, datetime

    when = datetime(2026, 7, 19, 14, 22, tzinfo=UTC)
    preview = ncmec.preview_payload(_files(), incident_urls=["https://ris.naa.gg/f/AQ.jpg"], incident_date=when)
    inc = preview["report"]["incident_summary"]
    assert inc["incident_date_time"].startswith("2026-07-19T14:22")
    assert inc["incident_date_time_description"] == "Time of the first reported media item uploaded to the bot."


def test_preview_chat_im_incident():
    """The chat incident records Telegram + the room label alongside the web page."""
    preview = ncmec.preview_payload(
        _files(), incident_urls=["https://ris.naa.gg/f/AQ.jpg"], chat_room_name="@ris_bot (bot DM)"
    )
    details = preview["report"]["internet_details"]
    chats = [d["chat_im_incident"] for d in details if "chat_im_incident" in d]
    assert len(chats) == 1
    assert chats[0]["chat_client"] == "Telegram"
    assert chats[0]["chat_room_name"] == "@ris_bot (bot DM)"


def test_preview_profile_bio_and_terms(monkeypatch):
    """profileBio comes from the reported_user dict; termsOfService from settings."""
    from reverse_image_search_bot import settings

    monkeypatch.setattr(settings, "NCMEC_TERMS_OF_SERVICE", "RIS terms here")
    preview = ncmec.preview_payload(
        _files(),
        incident_urls=["https://ris.naa.gg/f/AQ.jpg"],
        reported_user={"user_id": 5, "bio": "suspicious bio"},
    )
    assert preview["report"]["person_or_user_reported"]["profile_bio"] == "suspicious bio"
    assert preview["report"]["reporter"]["terms_of_service"] == "RIS terms here"


def test_preview_per_file_upload_timestamp_and_caption():
    """Each file carries its own uploadedToEspTimestamp; a caption goes to additional_info."""
    from datetime import UTC, datetime

    files = _files()
    files[0]["upload_time"] = datetime(2026, 7, 19, 14, 22, tzinfo=UTC)
    files[0]["caption"] = "look here"
    preview = ncmec.preview_payload(files, incident_urls=["https://ris.naa.gg/f/AQ.jpg"])
    f0 = preview["files"][0]
    assert f0["uploaded_to_esp_timestamp"].startswith("2026-07-19T14:22")
    assert f0["additional_info"] == ["User caption: look here"]
    # A file without an upload_time omits the timestamp (never faked to now).
    assert "uploaded_to_esp_timestamp" not in preview["files"][2]
