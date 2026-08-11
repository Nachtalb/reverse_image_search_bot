"""Tests for report preparation (take files offline) + the cleared state."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

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


@pytest.fixture
def env(abuse, tmp_path, monkeypatch):
    """Upload dir + base URL configured; returns (abuse, updir, mkfiles)."""
    from reverse_image_search_bot import settings

    updir = tmp_path / "uploads"
    updir.mkdir()
    # "uploader" key present so importing server (→ uploaders) works standalone.
    monkeypatch.setattr(settings, "UPLOADER", {"uploader": "local", "configuration": {"path": str(updir)}})
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")

    def mkfiles(user_id: int, n: int, prefix: str = "F"):
        abuse.record_user(user_id, username=f"u{user_id}")
        for i in range(n):
            fid = f"{prefix}{i}"
            abuse.record_file(fid, saved_filename=f"{fid}.jpg", user_id=user_id, file_type="photo")
            (updir / f"{fid}.jpg").write_bytes(b"img-" + fid.encode())

    return abuse, updir, mkfiles


def test_prepare_encrypts_every_file_and_takes_them_offline(env):
    from reverse_image_search_bot.abuse_report import crypto, prepare

    abuse, updir, mkfiles = env
    mkfiles(1, 30)
    result = prepare.prepare_report(1)
    assert result.ok
    assert result.encrypted == 30
    assert len(abuse.blob_meta(result.report_uuid)) == 30
    # No cap: every plaintext is gone from disk while the round is open.
    assert list(updir.iterdir()) == []
    # And the blobs really hold the plaintext, under P1.
    key = crypto.derive_key(result.p1 or "")
    b = abuse.report_blobs(result.report_uuid)[0]
    plain = crypto.decrypt_file(bytes(b["nonce"]), bytes(b["ciphertext"]), key)
    assert crypto.sha256_hex(plain) == b["plaintext_sha256"]


def test_restore_puts_files_back(env):
    from reverse_image_search_bot.abuse_report import prepare

    _abuse, updir, mkfiles = env
    mkfiles(1, 3)
    result = prepare.prepare_report(1)
    assert not (updir / "F0.jpg").exists()

    assert prepare.restore_report_files(result.report_uuid or "", result.p1 or "") is None
    assert (updir / "F0.jpg").read_bytes() == b"img-F0"
    assert (updir / "F2.jpg").read_bytes() == b"img-F2"


def test_restore_with_wrong_key_writes_nothing(env):
    from reverse_image_search_bot.abuse_report import prepare

    _abuse, updir, mkfiles = env
    mkfiles(1, 2)
    result = prepare.prepare_report(1)
    err = prepare.restore_report_files(result.report_uuid or "", "totally-wrong-key")
    assert "P1" in (err or "")
    assert list(updir.iterdir()) == []  # nothing scattered into the upload dir


def test_delete_user_files_removes_everything_on_disk(env):
    from reverse_image_search_bot.abuse_report import prepare

    _abuse, updir, mkfiles = env
    mkfiles(1, 3)
    mkfiles(2, 1, prefix="OTHER")
    assert prepare.delete_user_files(1) == 3
    assert not (updir / "F0.jpg").exists()
    assert (updir / "OTHER0.jpg").exists()  # other users untouched


def test_cleared_files_excluded_from_prepare(env):
    from reverse_image_search_bot.abuse_report import prepare

    abuse, _, mkfiles = env
    mkfiles(1, 3)
    abuse.set_files_cleared(["F0", "F1"])
    result = prepare.prepare_report(1)
    assert result.ok
    assert result.encrypted == 1
    assert abuse.blob_meta(result.report_uuid)[0]["file_unique_id"] == "F2"


def test_all_cleared_means_nothing_to_report(env):
    from reverse_image_search_bot.abuse_report import prepare

    abuse, _, mkfiles = env
    mkfiles(1, 2)
    abuse.set_files_cleared(["F0", "F1"])
    result = prepare.prepare_report(1)
    assert not result.ok
    assert "cleared" in (result.error or "")


@pytest.mark.asyncio
async def test_cancel_with_clear_files_marks_round_cleared(env, monkeypatch):
    from unittest.mock import AsyncMock

    from reverse_image_search_bot.abuse_report import prepare, server

    abuse, updir, mkfiles = env
    mkfiles(1, 2)
    result = prepare.prepare_report(1)
    uuid = result.report_uuid

    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    req = MagicMock(spec=web.Request)
    req.headers = {"X-Page-Secret": "pw"}
    req.query = {}
    req.match_info = {"uuid": uuid}
    req.app = {"bot": None}
    req.json = AsyncMock(return_value={"clear_files": True, "image_key": result.p1})
    await server.api_cancel(req)

    assert abuse.get_report(uuid)["status"] == abuse.REPORT_CANCELLED
    # Files restored to disk, but both marked cleared → a re-report finds nothing.
    assert (updir / "F0.jpg").exists()
    again = prepare.prepare_report(1)
    assert not again.ok
    assert "cleared" in (again.error or "")


@pytest.mark.asyncio
async def test_cancel_without_clear_keeps_files_reportable(env, monkeypatch):
    from unittest.mock import AsyncMock

    from reverse_image_search_bot.abuse_report import prepare, server

    _abuse, _, mkfiles = env
    mkfiles(1, 1)
    result = prepare.prepare_report(1)

    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    req = MagicMock(spec=web.Request)
    req.headers = {"X-Page-Secret": "pw"}
    req.query = {}
    req.match_info = {"uuid": result.report_uuid}
    req.app = {"bot": None}
    req.json = AsyncMock(return_value={"clear_files": False, "image_key": result.p1})
    await server.api_cancel(req)

    again = prepare.prepare_report(1)
    assert again.ok  # still reportable


@pytest.mark.asyncio
async def test_cancel_restores_files_and_rejects_wrong_key(env, monkeypatch):
    from unittest.mock import AsyncMock

    from reverse_image_search_bot.abuse_report import prepare, server

    abuse, updir, mkfiles = env
    mkfiles(1, 2)
    result = prepare.prepare_report(1)
    assert list(updir.iterdir()) == []

    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    req = MagicMock(spec=web.Request)
    req.headers = {"X-Page-Secret": "pw"}
    req.query = {}
    req.match_info = {"uuid": result.report_uuid}
    req.app = {"bot": None}

    # Wrong key: refused, blobs still intact, report still open.
    req.json = AsyncMock(return_value={"image_key": "nope"})
    with pytest.raises(web.HTTPBadRequest):
        await server.api_cancel(req)
    assert len(abuse.report_blobs(result.report_uuid)) == 2
    assert abuse.get_report(result.report_uuid)["status"] == abuse.REPORT_READY

    # Right key: files come back, blobs purged.
    req.json = AsyncMock(return_value={"image_key": result.p1})
    await server.api_cancel(req)
    assert (updir / "F0.jpg").read_bytes() == b"img-F0"
    assert (updir / "F1.jpg").read_bytes() == b"img-F1"
    assert abuse.report_blobs(result.report_uuid) == []


def test_filing_clears_unselected_files(env):
    """The api_submit clear step: unselected files in a filed round become cleared."""
    abuse, _, mkfiles = env
    mkfiles(1, 2)
    abuse.create_report("u", 1, "")
    abuse.add_report_blob(
        "u", file_unique_id="F0", saved_filename="F0.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    abuse.add_report_blob(
        "u", file_unique_id="F1", saved_filename="F1.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="2"
    )
    ids = {m["file_unique_id"]: m["id"] for m in abuse.blob_meta("u")}
    abuse.set_blob_selection("u", {ids["F0"]: "A1"})

    # Mirror the api_submit clear step.
    unselected = [b["file_unique_id"] for b in abuse.report_blobs("u") if not b["selected"]]
    assert abuse.set_files_cleared(unselected) == 1
    assert abuse.file_by_unique_id("F1")["cleared_at"] is not None
    assert abuse.file_by_unique_id("F0")["cleared_at"] is None
