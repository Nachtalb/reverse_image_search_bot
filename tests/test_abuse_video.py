"""Tests for the lazy video fetch + encrypt-on-disk report feature."""

from __future__ import annotations

import importlib
import os
import sqlite3
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def abuse(monkeypatch, tmp_path):
    import reverse_image_search_bot.settings as settings

    db_path = tmp_path / "abuse.db"
    monkeypatch.setattr(settings, "ABUSE_DB_PATH", db_path)
    import reverse_image_search_bot.config.abuse as a

    a._local.__dict__.clear()
    a._all_connections.clear()
    importlib.reload(a)
    monkeypatch.setattr(a, "ABUSE_DB_PATH", db_path)
    a._local.__dict__.clear()
    a._all_connections.clear()
    return a


def test_files_table_has_file_id_after_migration(tmp_path, monkeypatch):
    """Old files table (no file_id) migrates cleanly, keeping existing rows."""
    db = tmp_path / "old.db"
    c = sqlite3.connect(str(db))
    c.execute(
        "CREATE TABLE users(user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, "
        "language_code TEXT, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL, banned_at INTEGER)"
    )
    c.execute(
        "CREATE TABLE files(file_unique_id TEXT PRIMARY KEY, saved_filename TEXT NOT NULL, "
        "original_filename TEXT, file_type TEXT, upload_time INTEGER NOT NULL, user_id INTEGER NOT NULL, "
        "group_id INTEGER, channel_id INTEGER)"
    )
    c.execute("INSERT INTO users VALUES (7, 'u', 'U', NULL, NULL, 1000, 2000, NULL)")
    c.execute("INSERT INTO files VALUES ('u1','u1.jpg',NULL,'photo',1500,7,NULL,NULL)")
    c.commit()
    c.close()
    import reverse_image_search_bot.settings as settings

    monkeypatch.setattr(settings, "ABUSE_DB_PATH", db)
    import reverse_image_search_bot.config.abuse as a

    a._local.__dict__.clear()
    a._all_connections.clear()
    importlib.reload(a)
    monkeypatch.setattr(a, "ABUSE_DB_PATH", db)
    a._local.__dict__.clear()
    a._all_connections.clear()
    conn = a._get_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(files)")}
    assert "file_id" in cols
    rec = a.file_by_unique_id("u1")
    assert rec is not None
    assert rec["saved_filename"] == "u1.jpg"


def test_record_file_stores_file_id(abuse):
    abuse.record_user(9, username="v")
    abuse.record_file("v1", saved_filename="v1.jpg", user_id=9, file_type="video", file_id="BAADvid")
    rec = abuse.file_by_unique_id("v1")
    assert rec["file_id"] == "BAADvid"
    assert rec["file_type"] == "video"
    assert rec["created_at"] is not None and rec["created_at"] > 0


def test_blob_video_attach_and_meta(abuse):
    abuse.record_user(9, username="v")
    abuse.create_report("r1", 9, "")
    bid = abuse.add_report_blob(
        "r1", file_unique_id="v1", saved_filename="v1.jpg", nonce=b"n" * 12, ciphertext=b"c", plaintext_sha256="h"
    )
    assert isinstance(bid, int) and bid > 0
    # No video yet
    meta = abuse.blob_meta("r1")
    assert meta[0]["has_video"] is False
    # Attach one
    abuse.set_blob_video(
        bid, video_path="report_videos/v1.mp4.enc", video_nonce=b"x" * 12, video_sha256="vh", video_filename="v1.mp4"
    )
    meta = abuse.blob_meta("r1")
    assert meta[0]["has_video"] is True
    row = abuse.get_report_blob(bid)
    assert row["video_filename"] == "v1.mp4"
    assert row["video_sha256"] == "vh"


def test_blob_meta_has_video_only_for_real_videos(abuse):
    """has_video is True only for ACTUAL videos — never guessed from file_type.

    Regression: a jpg sent as a "document" must NOT be treated as a video. The
    viewer needs has_video True on first open for real videos (video_filename is
    only set after a fetch), so it derives from files.is_video via the LEFT JOIN —
    a flag set at ingest from the real Telegram type/mime, not the coarse
    file_type. Previously file_type=='document' wrongly flagged has_video.
    """
    abuse.record_user(9, username="v")
    # A real video upload.
    abuse.record_file("v1", saved_filename="v1.jpg", user_id=9, file_type="video", file_id="BAADvid", is_video=True)
    # A photo.
    abuse.record_file("p1", saved_filename="p1.jpg", user_id=9, file_type="photo", file_id="BAADpho")
    # THE BUG: a jpg image sent as a Telegram *document* — NOT a video.
    abuse.record_file("d1", saved_filename="d1.jpg", user_id=9, file_type="document", file_id="BAADdoc")
    abuse.create_report("r1", 9, "")
    for uid, sha in (("v1", "h"), ("p1", "h2"), ("d1", "h3")):
        abuse.add_report_blob(
            "r1",
            file_unique_id=uid,
            saved_filename=f"{uid}.jpg",
            nonce=b"n" * 12,
            ciphertext=b"c",
            plaintext_sha256=sha,
        )
    meta = {m["file_unique_id"]: m for m in abuse.blob_meta("r1")}
    assert meta["v1"]["has_video"] is True  # real video → offered before any fetch
    assert meta["p1"]["has_video"] is False  # photo → never a source video
    assert meta["d1"]["has_video"] is False  # jpg-as-document → NOT a video (the bug)
    # is_video is an internal join column, not part of the browser payload.
    assert "is_video" not in meta["v1"]
    # original_filename IS exposed (shown above the stored name in the UI).
    assert "original_filename" in meta["v1"]


@pytest.mark.asyncio
async def test_fetch_and_encrypt_video_roundtrip(abuse, monkeypatch, tmp_path):
    """The happy path: bot returns a small video, it gets encrypted on disk and
    decrypts back to the exact bytes with the report key."""
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import crypto
    from reverse_image_search_bot.abuse_report import video as vid

    # Point the uploader path at a temp dir.
    monkeypatch.setitem(settings.UPLOADER, "configuration", {"path": str(tmp_path)})

    abuse.record_user(9, username="v")
    abuse.record_file("v1", saved_filename="v1.mp4", user_id=9, file_type="video", file_id="BAADvid", is_video=True)
    abuse.create_report("r1", 9, "")
    bid = abuse.add_report_blob(
        "r1", file_unique_id="v1", saved_filename="v1.mp4", nonce=b"n" * 12, ciphertext=b"c", plaintext_sha256="h"
    )
    blob = abuse.get_report_blob(bid)

    real_video = b"\x00\x00\x00\x18ftypmp42" + os.urandom(4096)

    class FakeFile:
        file_size = len(real_video)
        file_path = "https://tg.example/file/v1.mp4"

    bot = AsyncMock()
    bot.get_file.return_value = FakeFile()

    # Stub the streaming download client to yield our bytes.
    class FakeResp:
        def raise_for_status(self):
            pass

        async def aiter_bytes(self, n):
            for i in range(0, len(real_video), n):
                yield real_video[i : i + n]

    class FakeStream:
        def __init__(self, data):
            self._d = data

        async def __aenter__(self):
            return FakeResp()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(vid._dl_client, "stream", lambda method, url: FakeStream(real_video))

    p1 = "test-key-123"
    res = await vid.fetch_and_encrypt_video(bot, blob, p1)
    assert res.ok, res.reason
    assert res.filename == "v1.mp4"

    # The encrypted file exists on disk; raw plaintext does NOT.
    row = abuse.get_report_blob(bid)
    assert row["video_path"].startswith("report_videos/")
    enc_path = tmp_path / row["video_path"]
    assert enc_path.is_file()
    assert enc_path.read_bytes() != real_video  # it's ciphertext

    # Decrypt with the report key → original bytes.
    key = crypto.derive_key(p1)
    plain = crypto.decrypt_file(bytes(row["video_nonce"]), enc_path.read_bytes(), key)
    assert plain == real_video
    assert crypto.sha256_hex(plain) == row["video_sha256"]


def test_ext_of():
    """Extension helper: from plain names, URLs with queries, and junk tails."""
    from reverse_image_search_bot.abuse_report.video import _ext_of

    assert _ext_of("clip.MP4") == "mp4"
    assert _ext_of("a/b/clip.webm") == "webm"
    assert _ext_of("https://tg.example/file/doc123.mkv?token=x") == "mkv"
    assert _ext_of("https://tg.example/file/video/12345") == ""  # no extension
    assert _ext_of("noext") == ""
    assert _ext_of("weird.thisisnotanext") == ""  # too long → rejected
    assert _ext_of(None) == ""
    assert _ext_of("") == ""


@pytest.mark.asyncio
async def test_video_extension_from_video_not_frame(abuse, monkeypatch, tmp_path):
    """Regression: the reported video must NOT inherit the frame's .jpg extension.

    The blob's saved_filename is the extracted FRAME (a .jpg). The video's real
    extension has to come from the uploader's original filename (preferred) or
    Telegram's container path — never the frame. Previously both filed as .jpg.
    """
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import video as vid

    monkeypatch.setitem(settings.UPLOADER, "configuration", {"path": str(tmp_path)})

    abuse.record_user(9, username="v")
    # Upload was a video: on-disk frame is .jpg, but the user's file was clip.webm.
    abuse.record_file(
        "v1",
        saved_filename="v1.jpg",
        user_id=9,
        original_filename="holiday clip.webm",
        file_type="video",
        file_id="BAADvid",
        is_video=True,
    )
    abuse.create_report("r1", 9, "")
    bid = abuse.add_report_blob(
        "r1", file_unique_id="v1", saved_filename="v1.jpg", nonce=b"n" * 12, ciphertext=b"c", plaintext_sha256="h"
    )
    blob = abuse.get_report_blob(bid)

    real_video = b"\x1aE\xdf\xa3" + os.urandom(2048)  # matroska/webm magic

    class FakeFile:
        file_size = len(real_video)
        file_path = "https://tg.example/file/v1.webm"

    bot = AsyncMock()
    bot.get_file.return_value = FakeFile()

    class FakeResp:
        def raise_for_status(self):
            pass

        async def aiter_bytes(self, n):
            for i in range(0, len(real_video), n):
                yield real_video[i : i + n]

    class FakeStream:
        async def __aenter__(self):
            return FakeResp()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(vid._dl_client, "stream", lambda method, url: FakeStream())

    res = await vid.fetch_and_encrypt_video(bot, blob, "k")
    assert res.ok, res.reason
    # Reported filename keeps the uploader's original name — NOT the frame's .jpg.
    assert res.filename == "holiday clip.webm"
    row = abuse.get_report_blob(bid)
    assert row["video_filename"] == "holiday clip.webm"
    # The ciphertext on disk uses the correct container extension, not .jpg.
    assert row["video_path"].endswith(".webm.enc")
    assert ".jpg" not in row["video_path"]


@pytest.mark.asyncio
async def test_fetch_video_rejects_non_video_document(abuse, monkeypatch, tmp_path):
    """A jpg sent as a *document* must never be fetched as a video.

    THE BUG: file_type=='document' was treated as video-capable, so a plain jpg
    document got a bogus VIDEO piece in the report. The gate now keys off the
    is_video flag (set at ingest), so a non-video document is rejected outright —
    no get_file, no video piece.
    """
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import video as vid

    monkeypatch.setitem(settings.UPLOADER, "configuration", {"path": str(tmp_path)})
    abuse.record_user(9, username="v")
    # A jpg image the user sent as a Telegram document (is_video defaults False).
    abuse.record_file("d1", saved_filename="d1.jpg", user_id=9, file_type="document", file_id="BAADdoc")
    abuse.create_report("rd", 9, "")
    bid = abuse.add_report_blob(
        "rd", file_unique_id="d1", saved_filename="d1.jpg", nonce=b"n" * 12, ciphertext=b"c", plaintext_sha256="h"
    )
    blob = abuse.get_report_blob(bid)

    bot = AsyncMock()
    res = await vid.fetch_and_encrypt_video(bot, blob, "k")
    assert not res.ok
    assert res.reason == "upload is not a video"
    bot.get_file.assert_not_called()  # never even attempted a download


@pytest.mark.asyncio
async def test_fetch_video_rejects_oversize(abuse, monkeypatch, tmp_path):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import video as vid

    monkeypatch.setitem(settings.UPLOADER, "configuration", {"path": str(tmp_path)})
    abuse.record_user(9, username="v")
    abuse.record_file("v2", saved_filename="v2.mp4", user_id=9, file_type="video", file_id="BAADbig", is_video=True)
    abuse.create_report("r2", 9, "")
    bid = abuse.add_report_blob(
        "r2", file_unique_id="v2", saved_filename="v2.mp4", nonce=b"n" * 12, ciphertext=b"c", plaintext_sha256="h"
    )
    blob = abuse.get_report_blob(bid)

    class FakeFile:
        file_size = 25 * 1024 * 1024  # 25 MB > 20 MB limit
        file_path = "https://tg.example/file/v2.mp4"

    bot = AsyncMock()
    bot.get_file.return_value = FakeFile()
    res = await vid.fetch_and_encrypt_video(bot, blob, "k")
    assert not res.ok
    assert "20 MB" in res.reason


@pytest.mark.asyncio
async def test_fetch_video_handles_deleted_message(abuse, monkeypatch, tmp_path):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import video as vid

    monkeypatch.setitem(settings.UPLOADER, "configuration", {"path": str(tmp_path)})
    abuse.record_user(9, username="v")
    abuse.record_file("v3", saved_filename="v3.mp4", user_id=9, file_type="video", file_id="BAADgone", is_video=True)
    abuse.create_report("r3", 9, "")
    bid = abuse.add_report_blob(
        "r3", file_unique_id="v3", saved_filename="v3.mp4", nonce=b"n" * 12, ciphertext=b"c", plaintext_sha256="h"
    )
    blob = abuse.get_report_blob(bid)

    bot = AsyncMock()
    bot.get_file.side_effect = Exception("Bad Request: file not found")
    res = await vid.fetch_and_encrypt_video(bot, blob, "k")
    assert not res.ok
    assert "no longer available" in res.reason
