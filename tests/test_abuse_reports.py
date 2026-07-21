"""Tests for reports/blobs DB layer and initData validation."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import time
from urllib.parse import urlencode

import pytest


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


def test_report_lifecycle(abuse):
    abuse.record_user(1, username="bad")
    abuse.create_report("uuid1", 1, "salt$hash")
    rep = abuse.get_report("uuid1")
    assert rep["status"] == abuse.REPORT_PREPARING
    assert rep["user_id"] == 1

    abuse.add_report_blob(
        "uuid1", file_unique_id="F1", saved_filename="F1.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="abc"
    )
    abuse.add_report_blob(
        "uuid1", file_unique_id="F2", saved_filename="F2.jpg", nonce=b"n", ciphertext=b"c2", plaintext_sha256="def"
    )
    assert len(abuse.blob_meta("uuid1")) == 2

    abuse.set_report_status("uuid1", abuse.REPORT_READY)
    assert abuse.get_report("uuid1")["status"] == abuse.REPORT_READY


def test_blob_selection_and_classification(abuse):
    abuse.record_user(1)
    abuse.create_report("u", 1, "h")
    abuse.add_report_blob(
        "u", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    abuse.add_report_blob(
        "u", file_unique_id="B", saved_filename="B.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="2"
    )
    meta = abuse.blob_meta("u")
    ids = [m["id"] for m in meta]

    abuse.set_blob_selection("u", {ids[0]: "A1"})
    sel = abuse.report_blobs("u", selected_only=True)
    assert len(sel) == 1
    assert sel[0]["classification"] == "A1"

    # Re-select replaces prior selection entirely.
    abuse.set_blob_selection("u", {ids[1]: "B2"})
    sel = abuse.report_blobs("u", selected_only=True)
    assert len(sel) == 1
    assert sel[0]["file_unique_id"] == "B"
    assert sel[0]["classification"] == "B2"


def test_record_file_stores_caption(abuse):
    """A caption sent with the media is stored and read back on the file row."""
    abuse.record_user(1)
    abuse.record_file("F", saved_filename="F.jpg", user_id=1, caption="look at this")
    rec = abuse.file_by_unique_id("F")
    assert rec["caption"] == "look at this"
    # No caption -> NULL, not an error.
    abuse.record_file("G", saved_filename="G.jpg", user_id=1)
    assert abuse.file_by_unique_id("G")["caption"] is None


def test_set_user_bio(abuse):
    """A user's bio can be stored after the fact and reads back via get_user."""
    abuse.record_user(7, username="x")
    assert abuse.get_user(7)["bio"] is None
    abuse.set_user_bio(7, "my telegram bio")
    assert abuse.get_user(7)["bio"] == "my telegram bio"
    # Updating the profile again must NOT clobber the bio (separate write path).
    abuse.record_user(7, username="x2")
    assert abuse.get_user(7)["bio"] == "my telegram bio"


def test_ncmec_id_and_filed(abuse):
    abuse.record_user(9)
    abuse.create_report("r", 9, "h")
    abuse.set_report_ncmec_id("r", 555111)
    assert abuse.get_report("r")["ncmec_report_id"] == 555111
    assert not abuse.has_report(9)
    abuse.mark_report_filed("r")
    assert abuse.get_report("r")["status"] == abuse.REPORT_FILED
    assert abuse.has_report(9)  # 🚩 lights up


def test_purge_blobs(abuse):
    abuse.record_user(1)
    abuse.create_report("p", 1, "h")
    abuse.add_report_blob(
        "p", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    assert abuse.purge_report_blobs("p") == 1
    assert abuse.blob_meta("p") == []


def test_active_report_for_user(abuse):
    abuse.record_user(1)
    abuse.create_report("act", 1, "h")
    abuse.set_report_status("act", abuse.REPORT_READY)
    assert abuse.active_report_for_user(1)["report_uuid"] == "act"
    abuse.set_report_status("act", abuse.REPORT_FILED)
    assert abuse.active_report_for_user(1) is None  # terminal → not active


def test_get_blob_cipher(abuse):
    abuse.record_user(1)
    abuse.create_report("g", 1, "h")
    abuse.add_report_blob(
        "g", file_unique_id="A", saved_filename="A.jpg", nonce=b"NONCE", ciphertext=b"CIPHER", plaintext_sha256="1"
    )
    bid = abuse.blob_meta("g")[0]["id"]
    row = abuse.get_blob_cipher("g", bid)
    assert bytes(row["nonce"]) == b"NONCE"
    assert bytes(row["ciphertext"]) == b"CIPHER"


def test_find_user_by_username(abuse):
    abuse.record_user(42, username="BadGuy")
    # case-insensitive, leading @ optional
    assert abuse.find_user_by_username("badguy") == 42
    assert abuse.find_user_by_username("@BadGuy") == 42
    assert abuse.find_user_by_username("@BADGUY") == 42
    assert abuse.find_user_by_username("nobody") is None
    assert abuse.find_user_by_username("") is None


def test_purge_unselected_blobs(abuse):
    abuse.record_user(1)
    abuse.create_report("p", 1, "h")
    abuse.add_report_blob(
        "p", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    abuse.add_report_blob(
        "p", file_unique_id="B", saved_filename="B.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="2"
    )
    ids = {m["file_unique_id"]: m["id"] for m in abuse.blob_meta("p")}
    abuse.set_blob_selection("p", {ids["A"]: "A1"})
    assert abuse.purge_unselected_blobs("p") == 1  # only B removed
    remaining = {b["file_unique_id"] for b in abuse.report_blobs("p")}
    assert remaining == {"A"}


# --- group / channel provenance ----------------------------------------------


def test_record_chat_and_get(abuse):
    abuse.record_chat(-100123, "group", title="Bad Group", username="badgrp")
    abuse.record_chat(-100999, "channel", title="Bad Channel")
    g = abuse.get_chat(-100123)
    c = abuse.get_chat(-100999)
    assert g["chat_type"] == "group" and g["title"] == "Bad Group" and g["username"] == "badgrp"
    assert c["chat_type"] == "channel" and c["title"] == "Bad Channel"
    assert abuse.get_chat(-1) is None


def test_record_chat_upsert_last_seen_wins(abuse):
    abuse.record_chat(-100123, "group", title="Old")
    abuse.record_chat(-100123, "group", title="New", username="grp")
    g = abuse.get_chat(-100123)
    assert g["title"] == "New" and g["username"] == "grp"


def test_record_file_with_group_and_channel(abuse):
    abuse.record_user(7)
    abuse.record_chat(-100123, "group", title="G")
    abuse.record_chat(-100999, "channel", title="C")
    abuse.record_file("F1", saved_filename="F1.jpg", user_id=7, group_id=-100123, channel_id=-100999)
    files = abuse.files_for_user(7)
    assert len(files) == 1
    assert files[0]["group_id"] == -100123
    assert files[0]["channel_id"] == -100999


def test_source_chats_for_user(abuse):
    abuse.record_user(7)
    abuse.record_chat(-100123, "group", title="G")
    abuse.record_chat(-100999, "channel", title="C")
    # one file via a group, one via a channel, one direct (no chat)
    abuse.record_file("F1", saved_filename="F1.jpg", user_id=7, group_id=-100123)
    abuse.record_file("F2", saved_filename="F2.jpg", user_id=7, channel_id=-100999)
    abuse.record_file("F3", saved_filename="F3.jpg", user_id=7)
    chats = abuse.source_chats_for_user(7)
    kinds = sorted(c["chat_type"] for c in chats)
    ids = sorted(c["chat_id"] for c in chats)
    assert kinds == ["channel", "group"]
    assert ids == [-100999, -100123]
    # a user with no chat-sourced files yields nothing
    abuse.record_user(8)
    abuse.record_file("F4", saved_filename="F4.jpg", user_id=8)
    assert abuse.source_chats_for_user(8) == []


def test_count_and_uploaders_for_chat(abuse):
    abuse.record_user(7)
    abuse.record_user(9)
    abuse.record_chat(-100123, "group", title="G")
    abuse.record_file("F1", saved_filename="F1.jpg", user_id=7, group_id=-100123)
    abuse.record_file("F2", saved_filename="F2.jpg", user_id=9, group_id=-100123)
    abuse.record_file("F3", saved_filename="F3.jpg", user_id=7)  # not via the group
    assert abuse.count_files_for_chat(-100123) == 2
    assert sorted(abuse.uploaders_for_chat(-100123)) == [7, 9]
    assert abuse.count_files_for_chat(-999) == 0
    assert abuse.uploaders_for_chat(-999) == []


def test_migration_adds_group_channel_columns(tmp_path, monkeypatch):
    """A files table created WITHOUT group_id/channel_id gets them added."""
    import importlib
    import sqlite3

    import reverse_image_search_bot.settings as settings

    db_path = tmp_path / "old_abuse.db"
    # Simulate an old-schema DB: files table lacking the new columns.
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE users (user_id INTEGER PRIMARY KEY, first_seen INTEGER, last_seen INTEGER)")
    conn.execute(
        "CREATE TABLE files (file_unique_id TEXT PRIMARY KEY, saved_filename TEXT NOT NULL, "
        "original_filename TEXT, file_type TEXT, upload_time INTEGER NOT NULL, "
        "user_id INTEGER NOT NULL REFERENCES users(user_id))"
    )
    conn.execute("INSERT INTO users VALUES (5, 0, 0)")
    conn.execute("INSERT INTO files VALUES ('OLD', 'OLD.jpg', NULL, NULL, 0, 5)")
    # A pre-existing real-video row and a document row, to check is_video backfill.
    conn.execute("INSERT INTO files VALUES ('VID', 'VID.jpg', NULL, 'video', 0, 5)")
    conn.execute("INSERT INTO files VALUES ('DOC', 'DOC.jpg', NULL, 'document', 0, 5)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "ABUSE_DB_PATH", db_path)
    import reverse_image_search_bot.config.abuse as ab

    ab._local.__dict__.clear()
    ab._all_connections.clear()
    importlib.reload(ab)
    monkeypatch.setattr(ab, "ABUSE_DB_PATH", db_path)
    ab._local.__dict__.clear()
    ab._all_connections.clear()

    # Opening the DB runs _ensure_schema → migration adds the columns.
    cols = {r["name"] for r in ab._get_conn().execute("PRAGMA table_info(files)")}
    assert "group_id" in cols and "channel_id" in cols
    # New columns from later migrations are added too (caption on files, bio on users).
    assert "caption" in cols
    ucols = {r["name"] for r in ab._get_conn().execute("PRAGMA table_info(users)")}
    assert "bio" in ucols
    # is_video column added and backfilled: real videos -> 1, everything else -> 0.
    assert "is_video" in cols
    vids = {f["file_unique_id"]: f["is_video"] for f in ab.files_for_user(5)}
    assert vids["VID"] == 1  # file_type 'video' backfilled to is_video=1
    assert vids["DOC"] == 0  # a document is NOT assumed to be a video
    assert vids["OLD"] == 0  # unknown/NULL type -> not a video
    # Existing row survived; new inserts with chat context work.
    ab.record_file("NEW", saved_filename="NEW.jpg", user_id=5, group_id=-100123, caption="hi")
    files = {f["file_unique_id"]: f for f in ab.files_for_user(5)}
    assert files["OLD"]["group_id"] is None
    assert files["OLD"]["caption"] is None
    assert files["NEW"]["group_id"] == -100123
    assert files["NEW"]["caption"] == "hi"


# --- initData validation ------------------------------------------------------


def _signed_init_data(bot_token: str, user_json: str, auth_date: int | None = None) -> str:
    auth_date = auth_date if auth_date is not None else int(time.time())
    params = {"user": user_json, "auth_date": str(auth_date), "query_id": "AAA"}
    check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    params["hash"] = h
    return urlencode(params)


def test_verify_init_data_valid():
    from reverse_image_search_bot.abuse_report.server import verify_init_data

    token = "123:abc"
    init = _signed_init_data(token, '{"id":42,"username":"a"}')
    user = verify_init_data(init, token)
    assert user and user["id"] == 42


def test_verify_init_data_bad_hash():
    from reverse_image_search_bot.abuse_report.server import verify_init_data

    init = _signed_init_data("123:abc", '{"id":42}')
    assert verify_init_data(init, "999:wrong") is None


def test_verify_init_data_expired():
    from reverse_image_search_bot.abuse_report.server import verify_init_data

    token = "123:abc"
    init = _signed_init_data(token, '{"id":42}', auth_date=int(time.time()) - 99999)
    assert verify_init_data(init, token, max_age=3600) is None


def test_verify_init_data_empty():
    from reverse_image_search_bot.abuse_report.server import verify_init_data

    assert verify_init_data("", "123:abc") is None
