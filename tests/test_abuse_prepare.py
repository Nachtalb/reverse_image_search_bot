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


def plaintexts(updir):
    """Uploaded plaintext files still on disk (ignores report_files/ ciphertext)."""
    return sorted(p.name for p in updir.iterdir() if p.is_file())


def ciphertexts(updir, report_uuid):
    """Encrypted blobs on disk for a report."""
    d = updir / "report_files" / report_uuid
    return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


def test_prepare_encrypts_every_file_and_takes_them_offline(env):
    from reverse_image_search_bot.abuse_report import crypto, prepare

    abuse, updir, mkfiles = env
    mkfiles(1, 30)
    result = prepare.prepare_report(1)
    assert result.ok
    assert result.encrypted == 30
    assert len(abuse.blob_meta(result.report_uuid)) == 30
    # No cap: every plaintext is gone from disk while the round is open.
    assert plaintexts(updir) == []
    # The ciphertext is on DISK, not in the DB — only filed files enter SQLite.
    assert len(ciphertexts(updir, result.report_uuid)) == 30
    key = crypto.derive_key(result.p1 or "")
    b = abuse.report_blobs(result.report_uuid)[0]
    assert bytes(b["ciphertext"]) == b""
    assert b["cipher_path"].startswith(f"report_files/{result.report_uuid}/")
    cipher = prepare.blob_ciphertext(b)
    assert cipher is not None
    plain = crypto.decrypt_file(bytes(b["nonce"]), cipher, key)
    assert crypto.sha256_hex(plain) == b["plaintext_sha256"]


def test_prepare_flags_indicator_files(env):
    """The file(s) the report was opened over are marked on their blobs."""
    from reverse_image_search_bot.abuse_report import prepare

    abuse, _updir, mkfiles = env
    mkfiles(1, 3)
    result = prepare.prepare_report(1, None, ["F1"])
    flagged = {b["saved_filename"] for b in abuse.blob_meta(result.report_uuid or "") if b["indicator"]}
    assert flagged == {"F1.jpg"}


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
    assert "image key" in (err or "")
    assert plaintexts(updir) == []  # nothing scattered into the upload dir


def test_delete_user_files_removes_everything_on_disk(env):
    from reverse_image_search_bot.abuse_report import prepare

    _abuse, updir, mkfiles = env
    mkfiles(1, 3)
    mkfiles(2, 1, prefix="OTHER")
    assert prepare.delete_user_files(1) == 3
    assert not (updir / "F0.jpg").exists()
    assert (updir / "OTHER0.jpg").exists()  # other users untouched


def test_prepare_reports_progress(env):
    from reverse_image_search_bot.abuse_report import prepare

    _abuse, _, mkfiles = env
    mkfiles(1, 5)
    seen = []
    result = prepare.prepare_report(1, lambda done, total: seen.append((done, total)))
    assert result.ok
    assert seen == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]


def test_ban_deletes_encrypted_leftovers_of_an_open_report(env):
    """Ban with a round still open: the ciphertext goes too, blobs and all."""
    from reverse_image_search_bot.abuse_report import prepare

    abuse, updir, mkfiles = env
    mkfiles(1, 3)
    result = prepare.prepare_report(1)
    assert len(ciphertexts(updir, result.report_uuid)) == 3

    prepare.delete_user_files(1)
    assert ciphertexts(updir, result.report_uuid) == []
    assert abuse.report_blobs(result.report_uuid) == []


def test_ban_keeps_a_filed_report_intact(env):
    """A filed report's blobs live in the DB and must survive the ban sweep."""
    from reverse_image_search_bot.abuse_report import prepare

    abuse, _, mkfiles = env
    mkfiles(1, 2)
    result = prepare.prepare_report(1)
    # Simulate filing: bytes into the DB, then the round is marked filed.
    for b in abuse.report_blobs(result.report_uuid):
        abuse.set_blob_ciphertext(b["id"], prepare.blob_ciphertext(b) or b"")
    abuse.mark_report_filed(result.report_uuid)

    prepare.delete_user_files(1)
    kept = abuse.report_blobs(result.report_uuid)
    assert len(kept) == 2
    assert all(bytes(b["ciphertext"]) for b in kept)


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
    assert plaintexts(updir) == []

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


# --- Re-fetching expired plaintext from Telegram before a round ---------------


def _tg_bot(payload: bytes = b"fresh", file_path: str = "https://api.telegram.org/file/x"):
    from unittest.mock import AsyncMock

    async def download_to_memory(buf):
        buf.write(payload)

    tg_file = MagicMock(file_path=file_path, download_to_memory=download_to_memory)
    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=tg_file)
    return bot


@pytest.mark.asyncio
async def test_refetch_restores_missing_image_and_round_includes_it(env):
    from reverse_image_search_bot.abuse_report import prepare

    abuse, _updir, mkfiles = env
    mkfiles(1, 2)
    abuse.record_file("GONE", saved_filename="GONE.jpg", user_id=1, file_type="photo", file_id="fid-gone")
    bot = _tg_bot(b"fresh-bytes")

    result = await prepare.fetch_and_prepare_report(bot, 1)

    bot.get_file.assert_awaited_once()
    assert bot.get_file.await_args.args[0] == "fid-gone"
    assert result.ok and result.encrypted == 3


@pytest.mark.asyncio
async def test_refetch_video_extracts_frame(env, monkeypatch):
    from reverse_image_search_bot.abuse_report import prepare
    from reverse_image_search_bot.commands import utils as cu

    abuse, updir, _mkfiles = env
    abuse.record_user(1)
    abuse.record_file("V", saved_filename="V.jpg", user_id=1, file_type="video", file_id="fid-v", is_video=True)
    urls = []

    async def fake_frame(url):
        urls.append(url)
        return b"\xff\xd8\xffframe"

    monkeypatch.setattr(cu, "_extract_frame_streaming", fake_frame)
    assert await prepare.refetch_missing(_tg_bot(file_path="https://tg/v.mp4"), 1) == 1
    assert urls == ["https://tg/v.mp4"]
    assert (updir / "V.jpg").read_bytes() == b"\xff\xd8\xffframe"


@pytest.mark.asyncio
async def test_refetch_failure_is_memoised_and_not_retried(env):
    from unittest.mock import AsyncMock

    from reverse_image_search_bot.abuse_report import prepare

    abuse, _updir, _mkfiles = env
    abuse.record_user(1)
    abuse.record_file("D", saved_filename="D.jpg", user_id=1, file_type="photo", file_id="fid-dead")
    bot = MagicMock()
    bot.get_file = AsyncMock(side_effect=RuntimeError("wrong file_id"))

    assert await prepare.refetch_missing(bot, 1) == 0
    assert abuse.file_by_unique_id("D")["video_error"] == prepare.FETCH_GONE
    assert await prepare.refetch_missing(bot, 1) == 0
    bot.get_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_refetch_skips_present_held_and_cleared(env):
    from reverse_image_search_bot.abuse_report import prepare

    abuse, _updir, mkfiles = env
    mkfiles(1, 1)  # F0 on disk
    abuse.record_file("C", saved_filename="C.jpg", user_id=1, file_type="photo", file_id="fid-c")
    abuse.set_files_cleared(["C"])
    abuse.record_file("H", saved_filename="H.jpg", user_id=1, file_type="photo", file_id="fid-h")
    abuse.set_file_hold("H", "after_ban", ("held/1/H.enc", b"n", "sha"))
    bot = _tg_bot()

    assert await prepare.refetch_missing(bot, 1) == 0
    bot.get_file.assert_not_awaited()
