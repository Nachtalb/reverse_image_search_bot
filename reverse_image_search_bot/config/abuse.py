"""Insert-only SQLite record of uploaders and uploaded files.

This exists to make a **proper NCMEC / abuse report** possible: it links an
uploaded file back to the Telegram user who sent it (name, username, upload
time) and preserves file provenance so a Cloudflare CSAM report — which only
gives us the on-disk filename — can be traced to an account and filed with the
required reporter/uploader details. It also keeps a durable, redundant copy of
the ban list that survives a cleared ``bot_data`` pickle.

Design:
- ``users``  — one row per Telegram user. Profile fields are upserted
  (last-seen wins); ``banned_at`` is a nullable ban timestamp (NULL = not
  banned). This is the durable, redundant copy of the ban list.
- ``files``  — one row per uploaded file, keyed on Telegram's
  ``file_unique_id`` (which is also the on-disk filename stem). Truly
  insert-only: ``INSERT OR IGNORE`` never rewrites an existing row.

Both tables use the same thread-local WAL connection pattern as ``config.db``.
"""

from __future__ import annotations

import atexit
import contextlib
import sqlite3
import threading
import time

from reverse_image_search_bot.settings import ABUSE_DB_PATH

_local = threading.local()
_all_connections: list[sqlite3.Connection] = []
_conn_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    """Return a thread-local SQLite connection with WAL mode + schema ensured."""
    if not hasattr(_local, "conn") or _local.conn is None:
        ABUSE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(ABUSE_DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        _ensure_schema(conn)
        with _conn_lock:
            _all_connections.append(conn)
        _local.conn = conn
    return _local.conn


def _close_all_connections() -> None:
    """Close all thread-local connections on interpreter shutdown."""
    with _conn_lock:
        for conn in _all_connections:
            with contextlib.suppress(Exception):
                conn.close()
        _all_connections.clear()


atexit.register(_close_all_connections)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY,
            username      TEXT,
            first_name    TEXT,
            last_name     TEXT,
            language_code TEXT,
            first_seen    INTEGER NOT NULL,
            last_seen     INTEGER NOT NULL,
            banned_at     INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            file_unique_id    TEXT PRIMARY KEY,
            saved_filename    TEXT NOT NULL,
            original_filename TEXT,
            file_type         TEXT,
            upload_time       INTEGER NOT NULL,
            user_id           INTEGER NOT NULL REFERENCES users(user_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_user ON files(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_saved ON files(saved_filename)")
    conn.commit()


def _now() -> int:
    return int(time.time())


def record_user(
    user_id: int,
    *,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    language_code: str | None = None,
) -> None:
    """Insert or update a user's profile (last-seen wins). Never touches ``banned_at``."""
    conn = _get_conn()
    now = _now()
    conn.execute(
        """
        INSERT INTO users (user_id, username, first_name, last_name, language_code, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username      = excluded.username,
            first_name    = excluded.first_name,
            last_name     = excluded.last_name,
            language_code = excluded.language_code,
            last_seen     = excluded.last_seen
        """,
        (user_id, username, first_name, last_name, language_code, now, now),
    )
    conn.commit()


def record_file(
    file_unique_id: str,
    *,
    saved_filename: str,
    user_id: int,
    original_filename: str | None = None,
    file_type: str | None = None,
) -> None:
    """Insert-only record of an uploaded file. Existing rows are left untouched."""
    conn = _get_conn()
    conn.execute(
        """
        INSERT OR IGNORE INTO files
            (file_unique_id, saved_filename, original_filename, file_type, upload_time, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (file_unique_id, saved_filename, original_filename, file_type, _now(), user_id),
    )
    conn.commit()


def set_banned(user_id: int, banned: bool) -> None:
    """Set or clear a user's ban timestamp. Creates a bare user row if needed."""
    conn = _get_conn()
    now = _now() if banned else None
    conn.execute(
        """
        INSERT INTO users (user_id, first_seen, last_seen, banned_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET banned_at = excluded.banned_at
        """,
        (user_id, _now(), _now(), now),
    )
    conn.commit()


def banned_user_ids() -> list[int]:
    """All currently-banned user IDs (``banned_at IS NOT NULL``). For startup sync."""
    conn = _get_conn()
    rows = conn.execute("SELECT user_id FROM users WHERE banned_at IS NOT NULL").fetchall()
    return [r["user_id"] for r in rows]


def is_banned(user_id: int) -> bool:
    conn = _get_conn()
    row = conn.execute("SELECT banned_at FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return bool(row and row["banned_at"] is not None)


def count_files(user_id: int) -> int:
    """Number of files recorded for a user."""
    conn = _get_conn()
    return conn.execute("SELECT COUNT(*) FROM files WHERE user_id = ?", (user_id,)).fetchone()[0]


def get_user(user_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def files_for_user(user_id: int) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM files WHERE user_id = ? ORDER BY upload_time", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def find_user_by_filename(filename: str) -> int | None:
    """Resolve the uploader from an on-disk filename or bare ``file_unique_id``.

    Cloudflare reports ``<file_unique_id>.<ext>`` — match both the saved
    filename and the bare id so either form works.
    """
    conn = _get_conn()
    stem = filename.rsplit(".", 1)[0]
    row = conn.execute(
        "SELECT user_id FROM files WHERE saved_filename = ? OR file_unique_id = ? OR file_unique_id = ?",
        (filename, filename, stem),
    ).fetchone()
    return row["user_id"] if row else None


def has_report(user_id: int) -> bool:
    """True if a filed report exists for this user.

    The ``reports`` table is created in Phase 2 (the report webview). Until then
    this returns False gracefully so the ban list / check command work now.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM reports WHERE user_id = ? AND status = 'finished' LIMIT 1",
            (user_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return False  # reports table not created yet
    return row is not None
