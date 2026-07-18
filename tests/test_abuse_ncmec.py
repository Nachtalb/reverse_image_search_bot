"""Tests for NCMEC report construction (reported subject: user + group/channel).

Pure model-building — no network. Verifies the uploader becomes the reported
person and that group/channel source context is stamped onto the report.
"""

from __future__ import annotations


def test_build_reported_subject_user_only(monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import ncmec

    monkeypatch.setattr(settings, "NCMEC_ESP_NAME", "")
    subj = ncmec.build_reported_subject(
        {"user_id": 833303928, "username": "baduser", "first_name": "Bad", "last_name": "Actor"},
        [],
    )
    assert subj is not None
    assert subj.esp_identifier == "833303928"
    assert subj.esp_service == "Reverse Image Search Bot"  # default when NCMEC_ESP_NAME unset
    assert subj.screen_name == "@baduser"
    assert "Bad Actor" in subj.display_name
    assert "https://t.me/baduser" in subj.profile_url
    assert subj.group_identifier is None


def test_build_reported_subject_with_group_and_channel(monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import ncmec

    monkeypatch.setattr(settings, "NCMEC_ESP_NAME", "RIS")
    subj = ncmec.build_reported_subject(
        {"user_id": 7, "username": "u"},
        [
            {"chat_id": -100123, "chat_type": "group", "title": "Bad Group", "username": None},
            {"chat_id": -100999, "chat_type": "channel", "title": "Bad Channel", "username": "badchan"},
        ],
    )
    assert subj is not None
    assert subj.esp_service == "RIS"
    assert subj.group_identifier is not None
    assert "group: Bad Group (id -100123)" in subj.group_identifier
    assert "channel: Bad Channel (id -100999)" in subj.group_identifier


def test_build_reported_subject_none_when_empty():
    from reverse_image_search_bot.abuse_report import ncmec

    assert ncmec.build_reported_subject(None, None) is None
    assert ncmec.build_reported_subject({}, []) is None


def test_build_report_attaches_reported_subject(monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import ncmec

    monkeypatch.setattr(settings, "NCMEC_REPORTER_EMAIL", "report@nachtalb.io")
    report = ncmec.build_report(
        incident_urls=["https://ris.naa.gg/f/A.jpg"],
        reported_user={"user_id": 7, "username": "u"},
        source_chats=[{"chat_id": -100123, "chat_type": "group", "title": "G", "username": None}],
    )
    assert report.person_or_user_reported is not None
    assert report.person_or_user_reported.esp_identifier == "7"
    # report still serializes to XML without error
    xml = report.to_xml()
    xml_text = xml.decode() if isinstance(xml, bytes) else xml
    assert "personOrUserReported" in xml_text
