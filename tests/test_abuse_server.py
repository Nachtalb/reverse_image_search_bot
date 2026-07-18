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


def _req(headers=None, match=None, json_body=None):
    r = MagicMock(spec=web.Request)
    r.headers = headers or {}
    r.query = {}
    r.match_info = match or {}
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


def test_delete_disk_files_keeps_blobs(abuse, monkeypatch, tmp_path):
    """On finish: plaintext files go from disk, but encrypted blobs are KEPT.

    New retention rule — the encrypted copies stay in the DB linked to the
    finished report (for further inspection / law enforcement); only the
    plaintext PVC files are unlinked.
    """
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    updir = tmp_path / "uploads"
    updir.mkdir()
    (updir / "A.jpg").write_bytes(b"plaintext image")
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}})

    abuse.record_user(1)
    abuse.create_report("u", 1, "h")
    abuse.add_report_blob(
        "u", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    rep = abuse.get_report("u")
    server._delete_disk_files(rep)
    assert not (updir / "A.jpg").exists()  # plaintext deleted from disk
    assert len(abuse.blob_meta("u")) == 1  # encrypted blob KEPT in the DB
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

    req = _req(headers={"X-Page-Secret": ""}, match={"uuid": "u"}, json_body={"image_key": p1})
    resp = await server.api_submit(req)
    import json

    data = json.loads(resp.text or "")
    assert data["status"] == abuse.REPORT_FILED
    assert data["ncmec_report_id"] == 987654
    submitted.assert_awaited_once()
    # report is filed, disk file gone, encrypted blob KEPT
    rep = abuse.get_report("u")
    assert rep["status"] == abuse.REPORT_FILED
    assert rep["ncmec_report_id"] == 987654
    assert not (updir / "A.jpg").exists()
    assert len(abuse.blob_meta("u")) == 1
