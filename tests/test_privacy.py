"""Tests for the user-facing data handling module (retention, takeout, erase)."""

from __future__ import annotations

import os
import time

import pytest

from reverse_image_search_bot import privacy, settings


@pytest.fixture
def updir(tmp_path, monkeypatch):
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(settings, "UPLOADER", {"uploader": "local", "configuration": {"path": str(d)}})
    monkeypatch.setattr(settings, "FILE_RETENTION_DAYS", 30)
    return d


def _touch(path, age_days: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    mtime = time.time() - age_days * 86400
    os.utime(path, (mtime, mtime))


def test_sweep_removes_only_expired_top_level_files(updir):
    _touch(updir / "old.jpg", 40)
    _touch(updir / "new.jpg", 1)
    _touch(updir / "report_videos" / "old.enc", 40)
    _touch(updir / "held" / "1" / "x.enc", 40)
    _touch(updir / "report_files" / "u" / "x.enc", 40)

    assert privacy.sweep_expired_uploads() == 1

    assert not (updir / "old.jpg").exists()
    assert (updir / "new.jpg").exists()
    assert (updir / "report_videos" / "old.enc").exists()
    assert (updir / "held" / "1" / "x.enc").exists()
    assert (updir / "report_files" / "u" / "x.enc").exists()


def test_sweep_noop_without_upload_dir(monkeypatch):
    monkeypatch.setattr(settings, "UPLOADER", {"uploader": "ssh", "configuration": {}})
    assert privacy.sweep_expired_uploads() == 0


@pytest.mark.asyncio
async def test_retention_job_runs_sweep(monkeypatch):
    from unittest.mock import MagicMock

    from reverse_image_search_bot import bot

    sweep = MagicMock(return_value=3)
    compact = MagicMock(return_value=0)
    monkeypatch.setattr(bot.privacy, "sweep_expired_uploads", sweep)
    monkeypatch.setattr(bot.abuse, "compact", compact)
    await bot.retention_job(MagicMock())
    sweep.assert_called_once_with()
    compact.assert_called_once_with()


@pytest.mark.asyncio
async def test_privacy_command_replies_with_policy():
    from unittest.mock import AsyncMock, MagicMock

    from reverse_image_search_bot.commands.privacy import privacy_command

    update = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    await privacy_command(update, MagicMock())
    text = update.effective_message.reply_text.call_args.args[0]
    assert text.startswith("<b>🔒 Privacy</b>")
    assert "report@nachtalb.io" in text
    assert len(text) <= 4096


# --- Takeout / erase ------------------------------------------------------------


@pytest.fixture
def abuse(tmp_path, monkeypatch):
    import importlib

    import reverse_image_search_bot.config.abuse as ab

    db_path = tmp_path / "abuse.db"
    monkeypatch.setattr(settings, "ABUSE_DB_PATH", db_path)
    ab._local.__dict__.clear()
    ab._all_connections.clear()
    importlib.reload(ab)
    monkeypatch.setattr(ab, "ABUSE_DB_PATH", db_path)
    ab._local.__dict__.clear()
    ab._all_connections.clear()
    return ab


@pytest.fixture
def world(abuse, updir):
    """User 1: two plain files, one blob-linked, one held, one expired (row only).
    Uploaded through group -100: F0 and LINKED."""
    from reverse_image_search_bot.config.chat_config import ChatConfig

    abuse.record_user(1, username="alice", first_name="Alice")
    abuse.record_chat(-100, "group", title="Grp")
    for fid, gid in (("F0", -100), ("F1", None), ("LINKED", -100), ("HELD", None)):
        abuse.record_file(fid, saved_filename=f"{fid}.jpg", user_id=1, file_type="photo", group_id=gid, file_id="x")
        (updir / f"{fid}.jpg").write_bytes(b"img-" + fid.encode())
    abuse.record_file("EXPIRED", saved_filename="EXPIRED.jpg", user_id=1, file_type="photo", file_id="x")
    abuse.create_report("rep", 1, "")
    abuse.add_report_blob("rep", file_unique_id="LINKED", saved_filename="LINKED.jpg", nonce=b"n", plaintext_sha256="h")
    (updir / "LINKED.jpg").unlink()  # prepare took it offline
    abuse.set_file_hold("HELD", "after_ban", ("held/1/HELD.enc", b"n", "sha"))
    abuse.set_report_status("rep", "cancelled")
    ChatConfig(1).language = "de"
    ChatConfig(-100).language = "fr"
    return abuse


def _zip_names(path):
    import zipfile

    with zipfile.ZipFile(path) as zf:
        return sorted(zf.namelist()), zf.read("data.json").decode()


def test_export_user_lists_history(world):
    data = privacy.export_data(1)
    assert data["user"]["username"] == "alice"
    assert data["settings"]["language"] == "de"
    assert [f["file_unique_id"] for f in data["files"]] == ["F0", "F1", "LINKED", "HELD", "EXPIRED"]


# The complete set of keys a takeout may ever contain. Anything not listed here
# is a leak — a new DB column is NOT exported until someone adds it deliberately.
ALLOWED_TOP = {"exported_at", "user", "chat", "settings", "files"}
ALLOWED_USER = {"user_id", "username", "first_name", "last_name", "language_code", "first_seen", "last_seen"}
ALLOWED_CHAT = {"chat_id", "chat_type", "title", "username", "first_seen", "last_seen"}
ALLOWED_FILE = {
    "file_unique_id",
    "original_filename",
    "file_type",
    "is_video",
    "upload_time",
    "caption",
    "user_id",
    "group_id",
    "channel_id",
}


@pytest.mark.parametrize("subject", [1, -100])
def test_export_contains_only_allowlisted_keys(world, subject):
    data = privacy.export_data(subject)
    assert set(data) <= ALLOWED_TOP
    if "user" in data:
        assert set(data["user"]) == ALLOWED_USER
    if "chat" in data:
        assert set(data["chat"]) == ALLOWED_CHAT
    for f in data["files"]:
        assert set(f) == ALLOWED_FILE


def test_takeout_bytes_never_contain_report_material(world, updir, tmp_path):
    """Seed every report-related field with a unique marker; none may reach the archive."""
    import zipfile

    abuse = world
    markers = {
        "bio": "MARK-BIO",
        "cleared": "MARK-CLEARED",
        "video_error": "MARK-VIDEO-ERROR",
        "hold_path": "held/1/MARK-HOLD.enc",
        "hold_sha256": "MARK-HOLD-SHA",
        "file_id": "MARK-FILE-ID",
        "report_uuid": "MARK-REPORT-UUID",
        "status_detail": "MARK-STATUS-DETAIL",
        "blob_sha": "MARK-BLOB-SHA",
        "blob_ciphertext": b"MARK-CIPHERTEXT",
        "linked_plaintext": b"MARK-LINKED-PLAINTEXT",
        "held_plaintext": b"MARK-HELD-PLAINTEXT",
    }
    abuse.set_user_bio(1, markers["bio"])
    abuse.set_banned(1, True)
    abuse.record_file("CL", saved_filename="CL.jpg", user_id=1, file_type="photo", file_id=markers["file_id"])
    (updir / "CL.jpg").write_bytes(b"img-CL")
    abuse.set_files_cleared(["CL"])
    abuse.set_file_video_error("F1", markers["video_error"])
    abuse.set_file_hold("F1", "during_investigation", (markers["hold_path"], b"n", markers["hold_sha256"]))
    abuse.create_report(markers["report_uuid"], 1, "")
    abuse.set_report_status(markers["report_uuid"], "error", markers["status_detail"])
    bid = abuse.add_report_blob(
        markers["report_uuid"],
        file_unique_id="F0",
        saved_filename="F0.jpg",
        nonce=b"n",
        plaintext_sha256=markers["blob_sha"],
        ciphertext=markers["blob_ciphertext"],
    )
    assert bid
    (updir / "F0.jpg").write_bytes(markers["linked_plaintext"])  # blob-linked → must not ship
    (updir / "HELD.jpg").write_bytes(markers["held_plaintext"])  # held → must not ship

    (archive,) = privacy.build_takeout(1, tmp_path)
    raw = archive.read_bytes()
    with zipfile.ZipFile(archive) as zf:
        raw += b"".join(zf.read(n) for n in zf.namelist())
    for name, marker in markers.items():
        needle = marker if isinstance(marker, bytes) else marker.encode()
        assert needle not in raw, f"{name} leaked into takeout"
    # …while legitimately exportable content is present, so the test is not vacuous.
    with zipfile.ZipFile(archive) as zf:
        assert b'"username": "alice"' in zf.read("data.json")
        assert zf.read("files/CL.jpg") == b"img-CL"  # cleared but unlinked → exportable


def test_takeout_ships_only_unlinked_files_on_disk(world, tmp_path):
    (parts,) = [privacy.build_takeout(1, tmp_path)]
    assert len(parts) == 1 and parts[0].name.startswith("takeout-1-") and parts[0].suffix == ".zip"
    names, _ = _zip_names(parts[0])
    assert names == ["data.json", "files/F0.jpg", "files/F1.jpg"]


def test_takeout_for_chat(world, tmp_path):
    data = privacy.export_data(-100)
    assert data["chat"]["title"] == "Grp" and data["settings"]["language"] == "fr"
    assert [f["file_unique_id"] for f in data["files"]] == ["F0", "LINKED"]
    names, _ = _zip_names(privacy.build_takeout(-100, tmp_path)[0])
    assert names == ["data.json", "files/F0.jpg"]


def test_takeout_splits_into_volumes(world, tmp_path, monkeypatch):
    monkeypatch.setattr(privacy, "PART_BYTES", 400)
    parts = privacy.build_takeout(1, tmp_path)
    assert len(parts) > 1
    assert [p.name[-4:] for p in parts] == [f".{n:03d}" for n in range(1, len(parts) + 1)]
    joined = tmp_path / "joined.zip"
    joined.write_bytes(b"".join(p.read_bytes() for p in parts))
    assert _zip_names(joined)[0] == ["data.json", "files/F0.jpg", "files/F1.jpg"]


def test_erase_reported_user_keeps_records_drops_plaintext(world, updir):
    from reverse_image_search_bot.config.chat_config import ChatConfig

    privacy.erase(1)
    assert not (updir / "F0.jpg").exists() and not (updir / "F1.jpg").exists()
    assert (updir / "HELD.jpg").exists()  # held → report material, untouched
    assert world.get_user(1) is not None
    assert len(world.files_for_user(1)) == 5
    assert ChatConfig(1).language is None


def test_erase_unreported_user_drops_everything(abuse, updir):
    from reverse_image_search_bot.config.chat_config import ChatConfig

    abuse.record_user(2, username="bob")
    abuse.record_file("B", saved_filename="B.jpg", user_id=2, file_type="photo")
    (updir / "B.jpg").write_bytes(b"b")
    ChatConfig(2).language = "it"

    privacy.erase(2)
    assert not (updir / "B.jpg").exists()
    assert abuse.get_user(2) is None and abuse.files_for_user(2) == []
    assert ChatConfig(2).language is None


def test_erase_chat_keeps_uploaders_records(world, updir):
    from reverse_image_search_bot.config.chat_config import ChatConfig

    privacy.erase(-100)
    assert not (updir / "F0.jpg").exists()
    assert (updir / "F1.jpg").exists()  # not uploaded through the chat
    assert world.get_chat(-100) is None
    assert len(world.files_for_user(1)) == 5
    assert ChatConfig(-100).language is None


def test_erase_unreported_user_with_held_file_keeps_that_row(abuse, updir):
    abuse.record_user(3)
    abuse.record_file("P", saved_filename="P.jpg", user_id=3, file_type="photo")
    abuse.record_file("H3", saved_filename="H3.jpg", user_id=3, file_type="photo")
    abuse.set_file_hold("H3", "after_ban", ("held/3/H3.enc", b"n", "sha"))

    privacy.erase(3)
    assert [f["file_unique_id"] for f in abuse.files_for_user(3)] == ["H3"]
    assert abuse.get_user(3) is not None
