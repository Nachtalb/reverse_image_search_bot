"""Tests for report preparation batching + the cleared (not-problematic) state."""

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


def test_prepare_caps_at_batch_and_reports_remaining(env):
    from reverse_image_search_bot.abuse_report import prepare

    abuse, _, mkfiles = env
    mkfiles(1, prepare.PREPARE_BATCH + 5)
    result = prepare.prepare_report(1)
    assert result.ok
    assert result.encrypted == prepare.PREPARE_BATCH
    assert result.remaining == 5
    assert len(abuse.blob_meta(result.report_uuid)) == prepare.PREPARE_BATCH
    assert prepare.pending_files(result.report_uuid or "") == 5


def test_extend_adds_next_batch_with_same_key(env):
    from reverse_image_search_bot.abuse_report import crypto, prepare

    abuse, _, mkfiles = env
    mkfiles(1, prepare.PREPARE_BATCH + 3)
    result = prepare.prepare_report(1)
    assert result.remaining == 3

    ext = prepare.extend_report(result.report_uuid or "", result.p1 or "")
    assert ext.ok
    assert ext.encrypted == 3
    assert ext.remaining == 0
    blobs = abuse.report_blobs(result.report_uuid)
    assert len(blobs) == prepare.PREPARE_BATCH + 3
    # New blobs decrypt with the ORIGINAL key.
    key = crypto.derive_key(result.p1 or "")
    last = blobs[-1]
    plain = crypto.decrypt_file(bytes(last["nonce"]), bytes(last["ciphertext"]), key)
    assert crypto.sha256_hex(plain) == last["plaintext_sha256"]


def test_extend_rejects_wrong_key(env):
    from reverse_image_search_bot.abuse_report import prepare

    abuse, _, mkfiles = env
    mkfiles(1, prepare.PREPARE_BATCH + 1)
    result = prepare.prepare_report(1)
    ext = prepare.extend_report(result.report_uuid or "", "totally-wrong-key")
    assert not ext.ok
    assert "P1" in (ext.error or "")
    assert len(abuse.report_blobs(result.report_uuid)) == prepare.PREPARE_BATCH


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
    req.json = AsyncMock(return_value={"clear_files": True})
    await server.api_cancel(req)

    assert abuse.get_report(uuid)["status"] == abuse.REPORT_CANCELLED
    # Disk files kept, but both marked cleared → a re-report finds nothing.
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
    req.json = AsyncMock(return_value={"clear_files": False})
    await server.api_cancel(req)

    again = prepare.prepare_report(1)
    assert again.ok  # still reportable


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
