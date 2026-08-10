"""Tests for the insert-only abuse-report DB."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def abuse(tmp_path, monkeypatch):
    """Fresh abuse module bound to an isolated DB file per test."""
    import reverse_image_search_bot.settings as settings

    db_path = tmp_path / "abuse.db"
    monkeypatch.setattr(settings, "ABUSE_DB_PATH", db_path)

    import reverse_image_search_bot.config.abuse as ab

    # Reset thread-local connections so the new path takes effect.
    ab._local.__dict__.clear()
    ab._all_connections.clear()
    importlib.reload(ab)
    monkeypatch.setattr(ab, "ABUSE_DB_PATH", db_path)
    ab._local.__dict__.clear()
    ab._all_connections.clear()
    return ab


def test_connection_uses_wal_with_synchronous_normal(abuse):
    """synchronous=FULL fsyncs every commit (~170 ms on the network PVC), which
    starves concurrent writers past busy_timeout -> "database is locked"."""
    conn = abuse._get_conn()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    # 1 == NORMAL. FULL (2) is the slow default this guards against.
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1


def test_lookup_queries_use_indexes_not_scans(abuse):
    """Both lookups were full table scans on the real DB. The username index
    only works if it carries the query's NOCASE collation."""
    abuse.record_user(1, username="alice")
    abuse.set_banned(2, True)
    conn = abuse._get_conn()

    plan = " ".join(
        r["detail"]
        for r in conn.execute(
            "EXPLAIN QUERY PLAN SELECT user_id FROM users WHERE username = ? COLLATE NOCASE", ("alice",)
        )
    )
    assert "SCAN" not in plan, plan
    assert "idx_users_username_nocase" in plan, plan

    plan = " ".join(
        r["detail"] for r in conn.execute("EXPLAIN QUERY PLAN SELECT user_id FROM users WHERE banned_at IS NOT NULL")
    )
    assert "SCAN" not in plan, plan
    assert "idx_users_banned" in plan, plan


def test_migrations_skip_scans_when_already_applied(abuse):
    """_ensure_schema runs on every new thread's connection. Once the DB is
    migrated the backfills are no-ops, but SQLite still scans the whole table to
    find that out — so they must be probe-gated, not run unconditionally."""
    abuse.record_user(1, username="alice")
    abuse.record_file("F1", saved_filename="F1.mp4", user_id=1, file_type="video")
    conn = abuse._get_conn()

    ran: list[str] = []
    # set_trace_callback sees every statement SQLite actually executes;
    # sqlite3.Connection.execute itself is read-only and can't be patched.
    conn.set_trace_callback(lambda sql: ran.append(" ".join(sql.split())))
    try:
        abuse._ensure_schema(conn)
    finally:
        conn.set_trace_callback(None)

    writes = [s for s in ran if s.upper().startswith(("UPDATE", "DELETE"))]
    assert writes == [], f"re-ran completed migrations: {writes}"


def test_backfill_runs_when_column_is_first_added(abuse, tmp_path):
    """The gate must not skip a backfill on a DB that genuinely needs it."""
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (user_id INTEGER PRIMARY KEY, first_seen INTEGER, last_seen INTEGER)")
    conn.execute(
        "CREATE TABLE files (file_unique_id TEXT PRIMARY KEY, saved_filename TEXT NOT NULL, "
        "original_filename TEXT, file_type TEXT, upload_time INTEGER NOT NULL, "
        "user_id INTEGER NOT NULL REFERENCES users(user_id))"
    )
    conn.execute("INSERT INTO users (user_id, first_seen, last_seen) VALUES (1, 42, 42)")
    conn.execute("INSERT INTO files VALUES ('V', 'V.mp4', NULL, 'video', 7, 1)")
    conn.execute("INSERT INTO files VALUES ('P', 'P.jpg', NULL, 'photo', 7, 1)")
    conn.commit()

    abuse._ensure_schema(conn)

    assert conn.execute("SELECT created_at FROM users WHERE user_id = 1").fetchone()[0] == 42
    rows = dict(conn.execute("SELECT file_unique_id, is_video FROM files").fetchall())
    assert rows == {"V": 1, "P": 0}
    conn.close()


def test_record_user_upserts_last_seen_wins(abuse):
    abuse.record_user(1, username="alice", first_name="Alice")
    abuse.record_user(1, username="alice2", first_name="Alice", last_name="B")
    user = abuse.get_user(1)
    assert user["username"] == "alice2"
    assert user["last_name"] == "B"
    assert user["banned_at"] is None


def test_record_file_is_insert_only(abuse):
    abuse.record_user(1, username="alice")
    abuse.record_file("FID1", saved_filename="FID1.jpg", user_id=1, file_type="photo")
    # Second call with a different saved_filename must NOT overwrite the row.
    abuse.record_file("FID1", saved_filename="OTHER.jpg", user_id=99)
    files = abuse.files_for_user(1)
    assert len(files) == 1
    assert files[0]["saved_filename"] == "FID1.jpg"
    assert files[0]["user_id"] == 1
    assert abuse.count_files(1) == 1
    assert abuse.count_files(99) == 0


def test_ban_toggle_and_sync(abuse):
    abuse.record_user(1, username="alice")
    assert abuse.is_banned(1) is False
    abuse.set_banned(1, True)
    assert abuse.is_banned(1) is True
    assert abuse.banned_user_ids() == [1]
    abuse.set_banned(1, False)
    assert abuse.is_banned(1) is False
    assert abuse.banned_user_ids() == []


def test_set_banned_creates_bare_user(abuse):
    # Banning a user we've never seen still records them (for startup sync).
    abuse.set_banned(555, True)
    assert abuse.is_banned(555) is True
    assert 555 in abuse.banned_user_ids()


def test_find_user_by_filename(abuse):
    abuse.record_user(7, username="bob")
    abuse.record_file("AQADxyz", saved_filename="AQADxyz.jpg", user_id=7)
    assert abuse.find_user_by_filename("AQADxyz.jpg") == 7  # full filename (Cloudflare form)
    assert abuse.find_user_by_filename("AQADxyz") == 7  # bare file_unique_id
    assert abuse.find_user_by_filename("nonexistent.jpg") is None


def test_has_report_false_without_reports_table(abuse):
    # Phase 1: no reports table exists yet — must degrade to False, not raise.
    abuse.record_user(1, username="alice")
    assert abuse.has_report(1) is False


def test_count_files_multiple(abuse):
    abuse.record_user(1)
    for i in range(3):
        abuse.record_file(f"F{i}", saved_filename=f"F{i}.jpg", user_id=1)
    assert abuse.count_files(1) == 3


def test_add_report_blob_is_idempotent(abuse):
    """A raced/retried extend can't create duplicate blobs (unique index + OR IGNORE)."""
    abuse.record_user(1)
    abuse.create_report("u", 1, "")
    first = abuse.add_report_blob(
        "u", file_unique_id="A", saved_filename="A.jpg", nonce=b"n1", ciphertext=b"c1", plaintext_sha256="h"
    )
    dup = abuse.add_report_blob(
        "u", file_unique_id="A", saved_filename="A.jpg", nonce=b"n2", ciphertext=b"c2", plaintext_sha256="h"
    )
    assert dup == first
    blobs = abuse.report_blobs("u")
    assert len(blobs) == 1
    assert bytes(blobs[0]["nonce"]) == b"n1"  # original kept, retry ignored


def test_set_file_video_error_first_wins(abuse):
    abuse.record_user(1)
    abuse.record_file("A", saved_filename="A.jpg", user_id=1)
    abuse.set_file_video_error("A", "too big")
    abuse.set_file_video_error("A", "something else")
    assert abuse.file_by_unique_id("A")["video_error"] == "too big"
