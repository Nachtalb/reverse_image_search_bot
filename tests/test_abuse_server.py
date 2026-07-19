"""Tests for the report server handlers (auth gating, cleanup) with mocks."""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web


@pytest.fixture
def abuse(tmp_path, monkeypatch):
    import reverse_image_search_bot.settings as settings

    db_path = tmp_path / "abuse.db"
    monkeypatch.setattr(settings, "ABUSE_DB_PATH", db_path)
    import reverse_image_search_bot.config.abuse as ab

    ab._local.__dict__.clear()
    ab._all_connections.clear()
    importlib.reload(ab)
    monkeypatch.setattr(ab, "ABUSE_DB_PATH", db_path)
    ab._local.__dict__.clear()
    ab._all_connections.clear()
    return ab


def _req(headers=None, match=None, json_body=None, app=None):
    r = MagicMock(spec=web.Request)
    r.headers = headers or {}
    r.query = {}
    r.match_info = match or {}
    r.app = app if app is not None else {"bot": None}
    if json_body is not None:
        r.json = AsyncMock(return_value=json_body)
    return r


@pytest.mark.asyncio
async def test_unlock_requires_admin(abuse, monkeypatch):
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(server, "_admin_from_request", lambda req: None)
    abuse.record_user(1)
    abuse.create_report("u", 1, "h")
    with pytest.raises(web.HTTPUnauthorized):
        await server.api_unlock(_req(match={"uuid": "u"}))


@pytest.mark.asyncio
async def test_unlock_wrong_page_password(abuse, monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "correct")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    abuse.record_user(1, username="x")
    abuse.create_report("u", 1, "")
    req = _req(headers={"X-Page-Secret": "wrong"}, match={"uuid": "u"})
    with pytest.raises(web.HTTPForbidden):
        await server.api_unlock(req)


@pytest.mark.asyncio
async def test_unlock_ok_returns_meta(abuse, monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "pw")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    abuse.record_user(7, username="baduser", first_name="Bad")
    abuse.create_report("u", 7, "")
    abuse.add_report_blob(
        "u", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    req = _req(headers={"X-Page-Secret": "pw"}, match={"uuid": "u"})
    resp = await server.api_unlock(req)
    import json

    data = json.loads(resp.text or "")
    assert data["user"]["id"] == 7
    assert data["user"]["username"] == "baduser"
    assert len(data["blobs"]) == 1


@pytest.mark.asyncio
async def test_status_needs_admin_but_not_secret(abuse, monkeypatch):
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    abuse.record_user(1)
    abuse.create_report("u", 1, "h")
    abuse.set_report_status("u", abuse.REPORT_READY)
    resp = await server.api_status(_req(match={"uuid": "u"}))
    import json

    assert json.loads(resp.text or "")["status"] == abuse.REPORT_READY


@pytest.mark.asyncio
async def test_select_persists(abuse, monkeypatch):
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    abuse.record_user(1)
    abuse.create_report("u", 1, "")
    abuse.add_report_blob(
        "u", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    bid = abuse.blob_meta("u")[0]["id"]
    req = _req(headers={"X-Page-Secret": "pw"}, match={"uuid": "u"}, json_body={"selections": {str(bid): "A1"}})
    await server.api_select(req)
    sel = abuse.report_blobs("u", selected_only=True)
    assert len(sel) == 1 and sel[0]["classification"] == "A1"


@pytest.mark.asyncio
async def test_cancel_purges_blobs_but_keeps_files_and_relation(abuse, monkeypatch, tmp_path):
    """Cancel = user did nothing wrong: keep disk files + filename->user relation.

    Only the encrypted blobs and the report status change; the original file on
    disk and the files-table row (find_user_by_filename) must survive.
    """
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    updir = tmp_path / "uploads"
    updir.mkdir()
    (updir / "A.jpg").write_bytes(b"plaintext image")
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}})

    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    abuse.record_user(1)
    # provenance relation: filename -> user
    abuse.record_file(file_unique_id="A", saved_filename="A.jpg", original_filename="orig.jpg", user_id=1)
    abuse.create_report("u", 1, "")
    abuse.add_report_blob(
        "u", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    req = _req(headers={"X-Page-Secret": "pw"}, match={"uuid": "u"})
    await server.api_cancel(req)

    # report cancelled, blobs gone
    assert abuse.get_report("u")["status"] == abuse.REPORT_CANCELLED
    assert abuse.blob_meta("u") == []
    # BUT: disk file kept, filename->user relation kept, user kept
    assert (updir / "A.jpg").exists()
    assert abuse.find_user_by_filename("A.jpg") == 1
    assert abuse.get_user(1) is not None


def test_cleanup_after_finish_keeps_reported_purges_unselected(abuse, monkeypatch, tmp_path):
    """On finish: reported files' plaintext deleted from disk, their blobs KEPT;
    non-reported files' blobs purged, their disk plaintext left alone.
    """
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    updir = tmp_path / "uploads"
    updir.mkdir()
    (updir / "A.jpg").write_bytes(b"reported image")
    (updir / "B.jpg").write_bytes(b"not reported image")
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}})

    abuse.record_user(1)
    abuse.create_report("u", 1, "h")
    abuse.add_report_blob(
        "u", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    abuse.add_report_blob(
        "u", file_unique_id="B", saved_filename="B.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="2"
    )
    # Report only A.
    ids = {m["file_unique_id"]: m["id"] for m in abuse.blob_meta("u")}
    abuse.set_blob_selection("u", {ids["A"]: "A1"})

    rep = abuse.get_report("u")
    server._cleanup_after_finish(rep)

    # A: plaintext deleted from disk, encrypted blob KEPT
    assert not (updir / "A.jpg").exists()
    kept = {b["file_unique_id"] for b in abuse.report_blobs("u")}
    assert kept == {"A"}
    # B: blob purged, disk plaintext left untouched (not part of the report)
    assert (updir / "B.jpg").exists()
    # user + report survive
    assert abuse.get_user(1) is not None
    assert abuse.get_report("u") is not None


@pytest.mark.asyncio
async def test_submit_files_and_finishes_and_keeps_blobs(abuse, monkeypatch, tmp_path):
    """/api/submit does submit+finish in one shot, deletes disk, keeps blobs.

    NCMEC is mocked; the encryption round-trips a real blob so the P1 decrypt +
    hash-verify path is exercised.
    """
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import crypto, ncmec, server

    updir = tmp_path / "uploads"
    updir.mkdir()
    plaintext = b"the bad image bytes"
    (updir / "A.jpg").write_bytes(plaintext)
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}})

    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")  # gate open

    # NCMEC filed → returns a report id + hex file ids
    submitted = AsyncMock(return_value=(987654, ["3a1d4fd4106b82499b7c93442aa7dca4"]))
    monkeypatch.setattr(ncmec, "submit_and_finish", submitted)

    p1 = "test-image-key"
    key = crypto.derive_key(p1)
    nonce, ct = crypto.encrypt_file(plaintext, key)

    abuse.record_user(1, username="bad")
    abuse.record_file(
        "A", saved_filename="A.jpg", user_id=1, original_filename="evidence-original.jpg", file_type="photo"
    )
    abuse.create_report("u", 1, "")
    abuse.add_report_blob(
        "u",
        file_unique_id="A",
        saved_filename="A.jpg",
        nonce=nonce,
        ciphertext=ct,
        plaintext_sha256=crypto.sha256_hex(plaintext),
    )
    bid = abuse.blob_meta("u")[0]["id"]
    abuse.set_blob_selection("u", {bid: "A1"})

    # Pass a live bot_data so the finish path can live-ban the uploader.
    bot_data: dict = {}
    req = _req(
        headers={"X-Page-Secret": ""},
        match={"uuid": "u"},
        json_body={"image_key": p1},
        app={"bot": None, "bot_data": bot_data},
    )
    resp = await server.api_submit(req)
    import json

    data = json.loads(resp.text or "")
    assert data["status"] == abuse.REPORT_FILED
    assert data["ncmec_report_id"] == 987654
    submitted.assert_awaited_once()
    # Per-file NCMEC fields: original_file_name keeps the uploader's original name,
    # location_of_file is our public copy's URL (two distinct facts, two fields).
    assert submitted.await_args is not None
    sent_files = submitted.await_args.args[0]
    assert len(sent_files) == 1
    assert sent_files[0]["filename"] == "evidence-original.jpg"
    assert "A.jpg" in sent_files[0]["location"]
    # report is filed, disk file gone, encrypted blob KEPT
    rep = abuse.get_report("u")
    assert rep["status"] == abuse.REPORT_FILED
    assert rep["ncmec_report_id"] == 987654
    assert not (updir / "A.jpg").exists()
    assert len(abuse.blob_meta("u")) == 1
    # Filing auto-bans the uploader: durable DB record AND the live in-memory list.
    assert abuse.is_banned(1)
    assert 1 in bot_data["banned_users"]


@pytest.mark.asyncio
async def test_reports_list(abuse, monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    abuse.record_user(1, username="bad")
    abuse.create_report("u1", 1, "")
    abuse.set_report_status("u1", abuse.REPORT_CANCELLED)  # cancelled reports still listed
    abuse.create_report("u2", 1, "")

    resp = await server.api_reports_list(_req(headers={"X-Page-Secret": ""}))
    import json

    data = json.loads(resp.text or "")
    uuids = {r["uuid"]: r["status"] for r in data["reports"]}
    assert uuids["u1"] == abuse.REPORT_CANCELLED
    assert uuids["u2"] == abuse.REPORT_PREPARING


@pytest.mark.asyncio
async def test_reports_create_by_username(abuse, monkeypatch, tmp_path):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    updir = tmp_path / "uploads"
    updir.mkdir()
    (updir / "A.jpg").write_bytes(b"img")
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}, "url": "https://x/f"})
    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)

    abuse.record_user(55, username="BadGuy")
    abuse.record_file("A", saved_filename="A.jpg", user_id=55)

    req = _req(headers={"X-Page-Secret": ""}, json_body={"target": "@badguy"})  # case-insensitive
    resp = await server.api_reports_create(req)
    import json

    data = json.loads(resp.text or "")
    assert data["ok"] is True
    assert data["user_id"] == 55
    assert data["encrypted"] == 1
    assert data["p1"]  # one-time key returned
    # a ready report now exists for the user
    assert abuse.active_report_for_user(55)["report_uuid"] == data["uuid"]


@pytest.mark.asyncio
async def test_reports_create_dms_p1(abuse, monkeypatch, tmp_path):
    """Creating a report via the app DMs the admin the P1 image key."""
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    updir = tmp_path / "uploads"
    updir.mkdir()
    (updir / "A.jpg").write_bytes(b"img")
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}, "url": "https://x/f"})
    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 4242)

    abuse.record_user(55, username="badguy")
    abuse.record_file("A", saved_filename="A.jpg", user_id=55)

    bot = MagicMock()
    bot.send_message = AsyncMock()
    req = _req(headers={"X-Page-Secret": ""}, json_body={"target": "55"}, app={"bot": bot})
    resp = await server.api_reports_create(req)
    import json

    data = json.loads(resp.text or "")
    bot.send_message.assert_awaited_once()
    args, _kwargs = bot.send_message.call_args
    assert args[0] == 4242  # DMed the requesting admin
    assert data["p1"] in args[1]  # the P1 key is in the message body


@pytest.mark.asyncio
async def test_reports_create_already_filed_message(abuse, monkeypatch, tmp_path):
    """Creating for a user whose files were already filed points at the NCMEC report."""
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    updir = tmp_path / "uploads"
    updir.mkdir()  # empty — no files on disk
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}, "url": "https://x/f"})
    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)

    abuse.record_user(55, username="badguy")
    abuse.record_file("A", saved_filename="A.jpg", user_id=55)  # recorded but not on disk
    # a prior FILED report with a kept blob
    abuse.create_report("old", 55, "")
    abuse.add_report_blob(
        "old", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    abuse.set_report_ncmec_id("old", 700200)
    abuse.mark_report_filed("old")

    req = _req(headers={"X-Page-Secret": ""}, json_body={"target": "A.jpg"})
    with pytest.raises(web.HTTPBadRequest) as exc:
        await server.api_reports_create(req)
    assert "700200" in (exc.value.text or "")  # points at the NCMEC report id


@pytest.mark.asyncio
async def test_reports_create_existing_returns_409(abuse, monkeypatch, tmp_path):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    updir = tmp_path / "uploads"
    updir.mkdir()
    (updir / "A.jpg").write_bytes(b"img")
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}, "url": "https://x/f"})
    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)

    abuse.record_user(55, username="badguy")
    abuse.record_file("A", saved_filename="A.jpg", user_id=55)
    abuse.create_report("existing", 55, "")
    abuse.set_report_status("existing", abuse.REPORT_READY)

    req = _req(headers={"X-Page-Secret": ""}, json_body={"target": "55"})
    resp = await server.api_reports_create(req)
    import json

    assert resp.status == 409
    data = json.loads(resp.text or "")
    assert data["existing_uuid"] == "existing"
