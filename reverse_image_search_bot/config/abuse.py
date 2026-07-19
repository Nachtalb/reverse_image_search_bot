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

# Telegram media types whose upload can carry a source video/animation. Photos
# never do. Used to offer the video in the report viewer before any fetch and to
# gate the lazy video-fetch path.
VIDEO_CAPABLE_FILE_TYPES = ("video", "gif", "sticker", "document")


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


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """Idempotently add a column to an existing table (simple forward migration)."""
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


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
            banned_at     INTEGER,
            created_at    INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            file_unique_id    TEXT PRIMARY KEY,
            saved_filename    TEXT NOT NULL,
            original_filename TEXT,
            file_type         TEXT,
            upload_time       INTEGER NOT NULL,
            user_id           INTEGER NOT NULL REFERENCES users(user_id),
            group_id          INTEGER,
            channel_id        INTEGER,
            file_id           TEXT,
            created_at        INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_user ON files(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_saved ON files(saved_filename)")

    # A chat (group/supergroup or channel) a file was uploaded through. Groups and
    # channels are reportable subjects too, so we keep their identity/profile the
    # same insert-or-update way as users. `chat_type` is 'group' or 'channel'.
    # `banned_at` mirrors the users table so a chat can be banned/flagged as well.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id    INTEGER PRIMARY KEY,
            chat_type  TEXT NOT NULL,
            title      TEXT,
            username   TEXT,
            first_seen INTEGER NOT NULL,
            last_seen  INTEGER NOT NULL,
            banned_at  INTEGER,
            created_at INTEGER
        )
    """)

    # --- migrations for DBs created before group/channel support (must run
    # BEFORE any index referencing the new columns) -------------------------
    _add_column_if_missing(conn, "files", "group_id", "INTEGER")
    _add_column_if_missing(conn, "files", "channel_id", "INTEGER")
    _add_column_if_missing(conn, "files", "file_id", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_group ON files(group_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_channel ON files(channel_id)")

    # created_at on every table (reports already has one). Backfill existing rows
    # from the closest pre-existing timestamp so old rows aren't left NULL.
    _add_column_if_missing(conn, "users", "created_at", "INTEGER")
    _add_column_if_missing(conn, "chats", "created_at", "INTEGER")
    _add_column_if_missing(conn, "files", "created_at", "INTEGER")
    conn.execute("UPDATE users SET created_at = first_seen WHERE created_at IS NULL")
    conn.execute("UPDATE chats SET created_at = first_seen WHERE created_at IS NULL")
    conn.execute("UPDATE files SET created_at = upload_time WHERE created_at IS NULL")

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
            classification  TEXT,
            video_path      TEXT,
            video_nonce     BLOB,
            video_sha256    TEXT,
            video_filename  TEXT,
            created_at      INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_blobs_report ON report_blobs(report_uuid)")
    # Forward migration: video columns for reports created before video support.
    _add_column_if_missing(conn, "report_blobs", "video_path", "TEXT")
    _add_column_if_missing(conn, "report_blobs", "video_nonce", "BLOB")
    _add_column_if_missing(conn, "report_blobs", "video_sha256", "TEXT")
    _add_column_if_missing(conn, "report_blobs", "video_filename", "TEXT")
    _add_column_if_missing(conn, "report_blobs", "created_at", "INTEGER")
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
        INSERT INTO users (user_id, username, first_name, last_name, language_code, first_seen, last_seen, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username      = excluded.username,
            first_name    = excluded.first_name,
            last_name     = excluded.last_name,
            language_code = excluded.language_code,
            last_seen     = excluded.last_seen
        """,
        (user_id, username, first_name, last_name, language_code, now, now, now),
    )
    conn.commit()


def record_file(
    file_unique_id: str,
    *,
    saved_filename: str,
    user_id: int,
    original_filename: str | None = None,
    file_type: str | None = None,
    group_id: int | None = None,
    channel_id: int | None = None,
    file_id: str | None = None,
) -> None:
    """Insert-only record of an uploaded file. Existing rows are left untouched.

    ``group_id`` / ``channel_id`` capture the chat the file was uploaded through
    (a message can involve a user and optionally a group and/or a channel).

    ``file_id`` is the Telegram file_id of the ORIGINAL upload (not the extracted
    frame) so the real file — e.g. the source video — can be re-downloaded later
    to report the actual uploaded media, not just a still frame.
    """
    conn = _get_conn()
    now = _now()
    conn.execute(
        """
        INSERT OR IGNORE INTO files
            (file_unique_id, saved_filename, original_filename, file_type,
             upload_time, user_id, group_id, channel_id, file_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_unique_id,
            saved_filename,
            original_filename,
            file_type,
            now,
            user_id,
            group_id,
            channel_id,
            file_id,
            now,
        ),
    )
    conn.commit()


def record_chat(
    chat_id: int,
    chat_type: str,
    *,
    title: str | None = None,
    username: str | None = None,
) -> None:
    """Insert or update a chat (group/channel) profile (last-seen wins).

    ``chat_type`` is 'group' (groups + supergroups) or 'channel'. Never touches
    ``banned_at``.
    """
    conn = _get_conn()
    now = _now()
    conn.execute(
        """
        INSERT INTO chats (chat_id, chat_type, title, username, first_seen, last_seen, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            chat_type = excluded.chat_type,
            title     = excluded.title,
            username  = excluded.username,
            last_seen = excluded.last_seen
        """,
        (chat_id, chat_type, title, username, now, now, now),
    )
    conn.commit()


def get_chat(chat_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
    return dict(row) if row else None


def set_banned(user_id: int, banned: bool) -> None:
    """Set or clear a user's ban timestamp. Creates a bare user row if needed."""
    conn = _get_conn()
    now = _now() if banned else None
    conn.execute(
        """
        INSERT INTO users (user_id, first_seen, last_seen, banned_at, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET banned_at = excluded.banned_at
        """,
        (user_id, _now(), _now(), now, _now()),
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


def source_chats_for_user(user_id: int) -> list[dict]:
    """Distinct group/channel chats a user's files were uploaded through.

    Returns chat rows (with ``chat_type``) for every distinct group_id/channel_id
    referenced by the user's files — the reportable group/channel subjects.
    """
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT DISTINCT c.* FROM chats c
        JOIN files f ON c.chat_id = f.group_id OR c.chat_id = f.channel_id
        WHERE f.user_id = ?
        """,
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def count_files_for_chat(chat_id: int) -> int:
    """Number of files uploaded through a given group/channel chat."""
    conn = _get_conn()
    return conn.execute(
        "SELECT COUNT(*) FROM files WHERE group_id = ? OR channel_id = ?",
        (chat_id, chat_id),
    ).fetchone()[0]


def uploaders_for_chat(chat_id: int) -> list[int]:
    """Distinct user ids who uploaded files through a given group/channel."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT user_id FROM files WHERE group_id = ? OR channel_id = ?",
        (chat_id, chat_id),
    ).fetchall()
    return [r["user_id"] for r in rows]


def get_user(user_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def files_for_user(user_id: int) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM files WHERE user_id = ? ORDER BY upload_time", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def file_by_unique_id(file_unique_id: str) -> dict | None:
    """Look up a recorded file row (carries the original ``file_id`` + type)."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM files WHERE file_unique_id = ?", (file_unique_id,)).fetchone()
    return dict(row) if row else None


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


def find_user_by_username(username: str) -> int | None:
    """Resolve a user id from a @username (case-insensitive; leading @ optional)."""
    uname = username.lstrip("@").strip()
    if not uname:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT user_id FROM users WHERE username = ? COLLATE NOCASE",
        (uname,),
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


def latest_filed_report_for_user(user_id: int) -> dict | None:
    """Most recent FILED report for a user, with its reported-file count.

    Used to explain "nothing on disk" — the files were already filed with NCMEC
    and deleted. Returns the report row plus ``reported_files`` (count of blobs
    that were part of that report, i.e. the ones kept), newest first.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM reports WHERE user_id = ? AND status = 'filed' "
            "ORDER BY finished_at DESC, created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    rep = dict(row)
    rep["reported_files"] = conn.execute(
        "SELECT COUNT(*) FROM report_blobs WHERE report_uuid = ?", (rep["report_uuid"],)
    ).fetchone()[0]
    return rep


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
) -> int:
    """Insert an image blob. Returns the new blob id."""
    conn = _get_conn()
    cur = conn.execute(
        """
        INSERT INTO report_blobs
            (report_uuid, file_unique_id, saved_filename, nonce, ciphertext, plaintext_sha256, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (report_uuid, file_unique_id, saved_filename, nonce, ciphertext, plaintext_sha256, _now()),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def set_blob_video(
    blob_id: int,
    *,
    video_path: str,
    video_nonce: bytes,
    video_sha256: str,
    video_filename: str,
) -> None:
    """Attach a lazily-fetched, encrypted-on-disk video to an existing image blob.

    The video ciphertext lives on disk (videos are large — never in the DB nor
    ever as raw plaintext on disk); only the nonce + hash + relative path are
    stored in the row.
    """
    conn = _get_conn()
    conn.execute(
        "UPDATE report_blobs SET video_path = ?, video_nonce = ?, video_sha256 = ?, video_filename = ? WHERE id = ?",
        (video_path, video_nonce, video_sha256, video_filename, blob_id),
    )
    conn.commit()


def get_report_blob(blob_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM report_blobs WHERE id = ?", (blob_id,)).fetchone()
    return dict(row) if row else None


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
    """Blob metadata WITHOUT ciphertext (for the gallery listing / status).

    ``has_video`` tells the browser to offer the video in the viewer. It is true
    if the video was already fetched (``video_filename`` set) OR the source upload
    is a video-capable type — so the viewer offers the video from the very first
    open, not only after a fetch has happened. The ciphertext itself (image in DB,
    video on disk) is fetched via the blob endpoints only after the admin supplies P1.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT b.id, b.file_unique_id, b.saved_filename, b.plaintext_sha256, b.selected, "
        "b.classification, b.video_filename, f.file_type, f.original_filename "
        "FROM report_blobs b LEFT JOIN files f ON f.file_unique_id = b.file_unique_id "
        "WHERE b.report_uuid = ? ORDER BY b.id",
        (report_uuid,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["has_video"] = bool(d.get("video_filename")) or (d.pop("file_type", None) in VIDEO_CAPABLE_FILE_TYPES)
        out.append(d)
    return out


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


def purge_unselected_blobs(report_uuid: str) -> int:
    """Delete only the NON-reported (unselected) blobs for a report.

    Used on finish: the reported files' encrypted blobs are KEPT (linked to the
    filed report for later inspection), while the ones the admin did not report
    are removed. Returns count deleted.
    """
    conn = _get_conn()
    cur = conn.execute("DELETE FROM report_blobs WHERE report_uuid = ? AND selected = 0", (report_uuid,))
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


def filed_report_stats() -> list[dict]:
    """Per-filed-report records for the statistics dashboard (FILED only).

    Cancelled/errored/in-flight reports are excluded — only successfully filed
    NCMEC reports count. Each record carries what the stats view needs to do all
    its own aggregation + period filtering client-side:

      * ``user_id``       — for the unique-user count
      * ``language``      — the uploader's Telegram UI language (may be None)
      * ``finished_at``   — when it was filed (drives year/month dropdowns); falls
                            back to ``updated_at`` then ``created_at`` for old rows
                            filed before ``finished_at`` was recorded
      * ``upload_times``  — unix ts of each reported file's ORIGINAL upload, for the
                            weekday×hour "when were they posted" heatmap
      * ``file_types``    — {file_type: count} of the reported files by their ACTUAL
                            recorded Telegram type (photo/video/sticker/gif/document/
                            unknown) — NOT forced into an image/video binary

    The reported files' encrypted blobs and their ``files`` rows are kept after
    filing, so the upload times remain resolvable.
    """
    conn = _get_conn()
    try:
        reps = conn.execute(
            "SELECT r.report_uuid, r.user_id, "
            "COALESCE(r.finished_at, r.updated_at, r.created_at) AS reported_at, "
            "u.language_code AS language "
            "FROM reports r LEFT JOIN users u ON u.user_id = r.user_id "
            "WHERE r.status = 'filed'"
        ).fetchall()
    except sqlite3.OperationalError:
        return []  # reports table not created yet
    if not reps:
        return []

    # Per-report reported files: upload times (heatmap) + a breakdown by the file's
    # ACTUAL recorded type. We do NOT infer "video" from capability flags — a
    # sticker is usually a static image, a document can be anything, so forcing
    # them into a video bucket would be wrong. Missing/NULL type → "unknown".
    uuids = [r["report_uuid"] for r in reps]
    placeholders = ",".join("?" * len(uuids))
    times: dict[str, list[int]] = {u: [] for u in uuids}
    file_types: dict[str, dict[str, int]] = {u: {} for u in uuids}
    rows = conn.execute(
        f"SELECT b.report_uuid, f.file_type, f.upload_time "
        f"FROM report_blobs b LEFT JOIN files f ON f.file_unique_id = b.file_unique_id "
        f"WHERE b.report_uuid IN ({placeholders})",
        uuids,
    ).fetchall()
    for row in rows:
        u = row["report_uuid"]
        if row["upload_time"] is not None:
            times[u].append(row["upload_time"])
        ftype = row["file_type"] or "unknown"
        file_types[u][ftype] = file_types[u].get(ftype, 0) + 1

    return [
        {
            "user_id": r["user_id"],
            "language": r["language"],
            "finished_at": r["reported_at"],
            "upload_times": times.get(r["report_uuid"], []),
            "file_types": file_types.get(r["report_uuid"], {}),
        }
        for r in reps
    ]
