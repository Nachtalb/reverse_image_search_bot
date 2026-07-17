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

    # A report round for one user. `report_uuid` is the URL token; `page_secret_hash`
    # gates the report page (P2, stored hashed — the image key P1 is NEVER stored).
    # `status` drives the live UI: preparing -> ready -> submitting -> filed / retracted
    #   / cancelled / error. `ncmec_report_id` is assigned by NCMEC on submit.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            report_uuid      TEXT PRIMARY KEY,
            user_id          INTEGER NOT NULL REFERENCES users(user_id),
            page_secret_hash TEXT NOT NULL,
            status           TEXT NOT NULL DEFAULT 'preparing',
            created_at       INTEGER NOT NULL,
            updated_at       INTEGER NOT NULL,
            ncmec_report_id  INTEGER,
            status_detail    TEXT,
            finished_at      INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id)")

    # Encrypted image blobs for a report (AES-GCM, key derived from P1 which is
    # never stored). Purged on finish/cancel. One row per file in the round.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS report_blobs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            report_uuid     TEXT NOT NULL REFERENCES reports(report_uuid),
            file_unique_id  TEXT NOT NULL,
            saved_filename  TEXT NOT NULL,
            nonce           BLOB NOT NULL,
            ciphertext      BLOB NOT NULL,
            plaintext_sha256 TEXT NOT NULL,
            selected        INTEGER NOT NULL DEFAULT 0,
            classification  TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_blobs_report ON report_blobs(report_uuid)")
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
    """True if a filed (finished) report exists for this user."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM reports WHERE user_id = ? AND status = 'filed' LIMIT 1",
            (user_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return False  # reports table not created yet
    return row is not None


# --- Reports & encrypted blobs -------------------------------------------------

# Report lifecycle states.
REPORT_PREPARING = "preparing"  # encrypting files into blobs
REPORT_READY = "ready"  # blobs ready, admin reviewing on the page
REPORT_SUBMITTING = "submitting"  # NCMEC submit/upload/file_info in progress
REPORT_REVIEW = "review"  # uploaded to NCMEC, awaiting final finish/retract
REPORT_FILED = "filed"  # finish() succeeded — report is with NCMEC
REPORT_RETRACTED = "retracted"  # retract() called
REPORT_CANCELLED = "cancelled"  # admin cancelled the whole round, blobs purged
REPORT_ERROR = "error"  # something failed; status_detail carries the message


def create_report(report_uuid: str, user_id: int, page_secret_hash: str) -> None:
    conn = _get_conn()
    now = _now()
    conn.execute(
        """
        INSERT INTO reports (report_uuid, user_id, page_secret_hash, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (report_uuid, user_id, page_secret_hash, REPORT_PREPARING, now, now),
    )
    conn.commit()


def add_report_blob(
    report_uuid: str,
    *,
    file_unique_id: str,
    saved_filename: str,
    nonce: bytes,
    ciphertext: bytes,
    plaintext_sha256: str,
) -> None:
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO report_blobs
            (report_uuid, file_unique_id, saved_filename, nonce, ciphertext, plaintext_sha256)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (report_uuid, file_unique_id, saved_filename, nonce, ciphertext, plaintext_sha256),
    )
    conn.commit()


def get_report(report_uuid: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM reports WHERE report_uuid = ?", (report_uuid,)).fetchone()
    return dict(row) if row else None


def set_report_status(report_uuid: str, status: str, detail: str | None = None) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE reports SET status = ?, status_detail = ?, updated_at = ? WHERE report_uuid = ?",
        (status, detail, _now(), report_uuid),
    )
    conn.commit()


def set_report_ncmec_id(report_uuid: str, ncmec_report_id: int) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE reports SET ncmec_report_id = ?, updated_at = ? WHERE report_uuid = ?",
        (ncmec_report_id, _now(), report_uuid),
    )
    conn.commit()


def mark_report_filed(report_uuid: str) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE reports SET status = ?, finished_at = ?, updated_at = ? WHERE report_uuid = ?",
        (REPORT_FILED, _now(), _now(), report_uuid),
    )
    conn.commit()


def report_blobs(report_uuid: str, *, selected_only: bool = False) -> list[dict]:
    conn = _get_conn()
    sql = "SELECT * FROM report_blobs WHERE report_uuid = ?"
    if selected_only:
        sql += " AND selected = 1"
    sql += " ORDER BY id"
    return [dict(r) for r in conn.execute(sql, (report_uuid,)).fetchall()]


def blob_meta(report_uuid: str) -> list[dict]:
    """Blob metadata WITHOUT ciphertext (for the gallery listing / status)."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, file_unique_id, saved_filename, plaintext_sha256, selected, classification "
        "FROM report_blobs WHERE report_uuid = ? ORDER BY id",
        (report_uuid,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_blob_cipher(report_uuid: str, blob_id: int) -> dict | None:
    """Nonce + ciphertext for one blob (for the browser to decrypt)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, nonce, ciphertext FROM report_blobs WHERE report_uuid = ? AND id = ?",
        (report_uuid, blob_id),
    ).fetchone()
    return dict(row) if row else None


def set_blob_selection(report_uuid: str, selections: dict[int, str | None]) -> None:
    """Apply the admin's per-blob selection + classification.

    ``selections`` maps blob id -> classification (``"A1"``/``"A2"``/``"B1"``/
    ``"B2"`` when selected, ``None`` when deselected). Blobs absent from the map
    are deselected.
    """
    conn = _get_conn()
    # Reset all to unselected first, then apply the given selections.
    conn.execute("UPDATE report_blobs SET selected = 0, classification = NULL WHERE report_uuid = ?", (report_uuid,))
    for blob_id, classification in selections.items():
        conn.execute(
            "UPDATE report_blobs SET selected = 1, classification = ? WHERE report_uuid = ? AND id = ?",
            (classification, report_uuid, blob_id),
        )
    conn.commit()


def purge_report_blobs(report_uuid: str) -> int:
    """Delete all encrypted blobs for a report. Returns count deleted."""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM report_blobs WHERE report_uuid = ?", (report_uuid,))
    conn.commit()
    return cur.rowcount


def active_report_for_user(user_id: int) -> dict | None:
    """The most recent non-terminal report for a user (preparing/ready/review/submitting)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM reports WHERE user_id = ? AND status IN (?, ?, ?, ?) ORDER BY created_at DESC LIMIT 1",
        (user_id, REPORT_PREPARING, REPORT_READY, REPORT_REVIEW, REPORT_SUBMITTING),
    ).fetchone()
    return dict(row) if row else None


def all_reports() -> list[dict]:
    """All reports, newest first — for the admin overview command."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT r.*, u.username FROM reports r LEFT JOIN users u ON u.user_id = r.user_id ORDER BY r.created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]
