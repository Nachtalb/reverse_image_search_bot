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

# The source every manually-created report (``/report``, the console) is filed
# under, and the one automated sources are contrasted with. Always exists and
# cannot be deleted.
DEFAULT_SOURCE = "sweep"


def _get_conn() -> sqlite3.Connection:
    """Return a thread-local SQLite connection with WAL mode + schema ensured."""
    if not hasattr(_local, "conn") or _local.conn is None:
        ABUSE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(ABUSE_DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        # Network block storage fsyncs slowly: synchronous=FULL costs ~170 ms per
        # commit here (p95 1.3 s), which piles writers up past busy_timeout and
        # surfaces as "database is locked". NORMAL is the documented-safe pairing
        # with WAL — durable across app crashes, only a power loss can lose the
        # last commits.
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=15000")
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


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, decl: str) -> bool:
    """Idempotently add a column to an existing table (simple forward migration).

    Returns True when the column was actually added, so a caller can run a
    one-shot backfill exactly once instead of on every connection.
    """
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        return True
    return False


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
    # Each backfill is gated on its ALTER: it is only meaningful the one time the
    # column appears. Probing for leftover NULLs instead would re-scan the whole
    # table on every connection to discover there is nothing to do.
    if _add_column_if_missing(conn, "users", "created_at", "INTEGER"):
        conn.execute("UPDATE users SET created_at = first_seen WHERE created_at IS NULL")
    if _add_column_if_missing(conn, "chats", "created_at", "INTEGER"):
        conn.execute("UPDATE chats SET created_at = first_seen WHERE created_at IS NULL")
    if _add_column_if_missing(conn, "files", "created_at", "INTEGER"):
        conn.execute("UPDATE files SET created_at = upload_time WHERE created_at IS NULL")

    # A user's Telegram bio (fetched best-effort at report time) and a per-file
    # caption (text sent alongside the media, if any) — both reportable to NCMEC.
    _add_column_if_missing(conn, "users", "bio", "TEXT")
    _add_column_if_missing(conn, "files", "caption", "TEXT")

    # Whether the upload is ACTUALLY a video/animation (has a real source video),
    # decided at ingest from the Telegram type/mime — NOT guessed from the coarse
    # file_type. A jpg sent as a "document" is not a video. Backfill the
    # unambiguous cases: Video -> file_type 'video', Animation -> 'gif' are always
    # real videos. Documents/stickers are left 0 (can't know retroactively; the
    # safe default is "not a video" so we never invent a bogus video piece). Rows
    # that already have a fetched video keep it via video_filename regardless.
    #
    # Gated on the column being NEW rather than on the rows, because is_video is
    # set per-file at ingest: a legitimately-0 'video' row would otherwise make
    # the backfill re-run (and re-scan) on every connection forever.
    is_video_added = _add_column_if_missing(conn, "files", "is_video", "INTEGER NOT NULL DEFAULT 0")
    if is_video_added:
        conn.execute("UPDATE files SET is_video = 1 WHERE file_type IN ('video', 'gif')")

    # A file the admin marked as NOT problematic ("cleared") — excluded from
    # report preparation just like already-filed pieces. Set from the cancel
    # dialog, or automatically for unselected files when a report is filed.
    _add_column_if_missing(conn, "files", "cleared_at", "INTEGER")

    # A PERMANENT source-video fetch failure for this file (over the 20 MB bot
    # limit, or message deleted). Once set, fetch attempts are skipped — no
    # retry storm and no repeated admin warnings on every review/submit.
    _add_column_if_missing(conn, "files", "video_error", "TEXT")

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

    # Where a report came from: the manual sweep (/report, the console) or an
    # automated feed pushing through the ingest API (Cloudflare CSAM detection,
    # Cybertip.ca, …). A source must exist before it can be used; `sweep` is
    # seeded here so there is always one and old rows have somewhere to point.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS report_sources (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            created_at INTEGER NOT NULL
        )
    """)
    conn.execute("INSERT OR IGNORE INTO report_sources (name, created_at) VALUES (?, ?)", (DEFAULT_SOURCE, _now()))
    # Backfill gated on the ALTER: only meaningful the one time the column
    # appears, and every later report gets a source at insert time.
    if _add_column_if_missing(conn, "reports", "source_id", "INTEGER REFERENCES report_sources(id)"):
        conn.execute("UPDATE reports SET source_id = (SELECT id FROM report_sources WHERE name = ?)", (DEFAULT_SOURCE,))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_source ON reports(source_id)")

    # API keys for the ingest endpoint. Only the SHA-256 of the key is stored —
    # the plaintext is shown once at creation/rotation and never again; the
    # masked `preview` is what every later read returns.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            key_hash     TEXT NOT NULL UNIQUE,
            key_preview  TEXT NOT NULL,
            created_at   INTEGER NOT NULL,
            rotated_at   INTEGER,
            last_used_at INTEGER
        )
    """)

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
    # Where a blob's image ciphertext lives while the report is open: on disk,
    # under the upload PVC (`cipher_path`), NOT in SQLite. Only the files that
    # actually get FILED are moved into the `ciphertext` column on finish. The
    # column stays NOT NULL (old DBs can't drop it) — an empty blob plus a set
    # `cipher_path` means "on disk"; see prepare.blob_ciphertext().
    _add_column_if_missing(conn, "report_blobs", "cipher_path", "TEXT")
    # One blob per file per report. A raced extend (e.g. client retry during a
    # locked-DB episode) used to insert duplicates; drop any existing ones (keep
    # the lowest id) so the unique index can be created on old DBs. Once that
    # index exists it enforces the constraint, so duplicates are impossible and
    # the scanning DELETE never needs to run again.
    has_unique_blob_index = (
        conn.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_blobs_report_file'").fetchone()
        is not None
    )
    if not has_unique_blob_index:
        conn.execute(
            "DELETE FROM report_blobs WHERE id NOT IN "
            "(SELECT MIN(id) FROM report_blobs GROUP BY report_uuid, file_unique_id)"
        )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_blobs_report_file ON report_blobs(report_uuid, file_unique_id)")
    # Forward migration: video columns for reports created before video support.
    _add_column_if_missing(conn, "report_blobs", "video_path", "TEXT")
    _add_column_if_missing(conn, "report_blobs", "video_nonce", "BLOB")
    _add_column_if_missing(conn, "report_blobs", "video_sha256", "TEXT")
    _add_column_if_missing(conn, "report_blobs", "video_filename", "TEXT")
    _add_column_if_missing(conn, "report_blobs", "created_at", "INTEGER")
    # Marks the file(s) the report was actually opened over (the Cloudflare URL
    # or filename the admin pasted), so they stay distinguishable in the gallery
    # from the rest of the user's material.
    _add_column_if_missing(conn, "report_blobs", "indicator", "INTEGER NOT NULL DEFAULT 0")

    # User lookup indexes. Created AFTER every column migration above — an old DB
    # has no `username` column when this function starts, and indexing a
    # not-yet-added column fails. Measured on a copy of the production DB
    # (5.8k users): username lookup 1.07 ms -> 0.08 ms, banned listing
    # 1.57 ms -> 0.12 ms; both were full table scans. The username index must
    # carry the query's NOCASE collation or SQLite can't use it. The banned
    # index is partial — banned users are a tiny fraction of the table.
    _add_column_if_missing(conn, "users", "username", "TEXT")
    _add_column_if_missing(conn, "users", "banned_at", "INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username_nocase ON users(username COLLATE NOCASE)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_banned ON users(banned_at) WHERE banned_at IS NOT NULL")
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
    with conn:
        now = _now()
        conn.execute(
            """
            INSERT INTO users
                (user_id, username, first_name, last_name, language_code, first_seen, last_seen, created_at)
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


def set_user_bio(user_id: int, bio: str | None) -> None:
    """Store a user's Telegram bio (fetched best-effort at report time).

    Only updates an existing row; a no-op if the user isn't recorded yet.
    """
    conn = _get_conn()
    with conn:
        conn.execute("UPDATE users SET bio = ? WHERE user_id = ?", (bio, user_id))


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
    caption: str | None = None,
    is_video: bool = False,
) -> None:
    """Insert-only record of an uploaded file. Existing rows are left untouched.

    ``group_id`` / ``channel_id`` capture the chat the file was uploaded through
    (a message can involve a user and optionally a group and/or a channel).

    ``file_id`` is the Telegram file_id of the ORIGINAL upload (not the extracted
    frame) so the real file — e.g. the source video — can be re-downloaded later
    to report the actual uploaded media, not just a still frame.

    ``caption`` is the text the user sent alongside the media, if any — kept as
    provenance/evidence and reported to NCMEC.

    ``is_video`` records whether the upload is ACTUALLY a video/animation (decided
    at ingest from the Telegram type/mime). A jpg sent as a document is NOT a
    video; only set this when there is a genuine source video to fetch/report.
    """
    conn = _get_conn()
    with conn:
        now = _now()
        conn.execute(
            """
            INSERT OR IGNORE INTO files
                (file_unique_id, saved_filename, original_filename, file_type,
                 upload_time, user_id, group_id, channel_id, file_id, caption, is_video, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                caption,
                1 if is_video else 0,
                now,
            ),
        )


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
    with conn:
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


def get_chat(chat_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
    return dict(row) if row else None


def set_banned(user_id: int, banned: bool) -> None:
    """Set or clear a user's ban timestamp. Creates a bare user row if needed."""
    conn = _get_conn()
    with conn:
        now = _now() if banned else None
        conn.execute(
            """
            INSERT INTO users (user_id, first_seen, last_seen, banned_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET banned_at = excluded.banned_at
            """,
            (user_id, _now(), _now(), now, _now()),
        )


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


def set_file_video_error(file_unique_id: str, reason: str) -> None:
    """Record a permanent source-video fetch failure (only the first one wins)."""
    conn = _get_conn()
    with conn:
        conn.execute(
            "UPDATE files SET video_error = ? WHERE file_unique_id = ? AND video_error IS NULL",
            (reason, file_unique_id),
        )


def set_files_cleared(file_unique_ids: list[str]) -> int:
    """Mark files as cleared (not problematic). Returns count updated.

    Cleared files are excluded from report preparation, like filed pieces.
    """
    if not file_unique_ids:
        return 0
    conn = _get_conn()
    with conn:
        placeholders = ",".join("?" * len(file_unique_ids))
        cur = conn.execute(
            f"UPDATE files SET cleared_at = ? WHERE file_unique_id IN ({placeholders}) AND cleared_at IS NULL",
            [_now(), *file_unique_ids],
        )
    return cur.rowcount


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
REPORT_DELETED = "deleted"  # selected files destroyed, rest restored; nothing filed
REPORT_ERROR = "error"  # something failed; status_detail carries the message


def create_report(report_uuid: str, user_id: int, page_secret_hash: str, source_id: int | None = None) -> None:
    conn = _get_conn()
    with conn:
        now = _now()
        conn.execute(
            """
            INSERT INTO reports (report_uuid, user_id, page_secret_hash, status, created_at, updated_at, source_id)
            VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, (SELECT id FROM report_sources WHERE name = ?)))
            """,
            (report_uuid, user_id, page_secret_hash, REPORT_PREPARING, now, now, source_id, DEFAULT_SOURCE),
        )


# --- report sources -----------------------------------------------------------


def list_sources() -> list[dict]:
    """All sources with their report counts, oldest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT s.id, s.name, s.created_at, COUNT(r.report_uuid) AS reports "
        "FROM report_sources s LEFT JOIN reports r ON r.source_id = s.id "
        "GROUP BY s.id ORDER BY s.id"
    ).fetchall()
    return [dict(r) for r in rows]


def get_source_by_name(name: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM report_sources WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def add_source(name: str) -> int:
    """Create a source. Raises ``sqlite3.IntegrityError`` if the name is taken."""
    conn = _get_conn()
    with conn:
        cur = conn.execute("INSERT INTO report_sources (name, created_at) VALUES (?, ?)", (name, _now()))
    return int(cur.lastrowid or 0)


def delete_source(source_id: int) -> str | None:
    """Delete a source. Returns an error string when it must be kept.

    The default source is permanent (reports fall back to it), and a source that
    already has reports is kept so the statistics stay attributable.
    """
    conn = _get_conn()
    row = conn.execute("SELECT name FROM report_sources WHERE id = ?", (source_id,)).fetchone()
    if not row:
        return "source not found"
    if row["name"] == DEFAULT_SOURCE:
        return f"the default source ({DEFAULT_SOURCE}) cannot be deleted"
    used = conn.execute("SELECT COUNT(*) AS n FROM reports WHERE source_id = ?", (source_id,)).fetchone()["n"]
    if used:
        return f"source has {used} report(s) — kept so the statistics stay attributable"
    with conn:
        conn.execute("DELETE FROM report_sources WHERE id = ?", (source_id,))
    return None


# --- ingest API keys ----------------------------------------------------------


def list_api_keys() -> list[dict]:
    """All API keys, newest first. Never returns the key itself — only its mask."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, name, key_preview, created_at, rotated_at, last_used_at FROM api_keys ORDER BY id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def add_api_key(name: str, key_hash: str, key_preview: str) -> int:
    conn = _get_conn()
    with conn:
        cur = conn.execute(
            "INSERT INTO api_keys (name, key_hash, key_preview, created_at) VALUES (?, ?, ?, ?)",
            (name, key_hash, key_preview, _now()),
        )
    return int(cur.lastrowid or 0)


def rotate_api_key(key_id: int, key_hash: str, key_preview: str) -> bool:
    """Replace a key's secret in place (name + creation date kept)."""
    conn = _get_conn()
    with conn:
        cur = conn.execute(
            "UPDATE api_keys SET key_hash = ?, key_preview = ?, rotated_at = ?, last_used_at = NULL WHERE id = ?",
            (key_hash, key_preview, _now(), key_id),
        )
    return cur.rowcount > 0


def delete_api_key(key_id: int) -> bool:
    conn = _get_conn()
    with conn:
        cur = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
    return cur.rowcount > 0


def api_key_by_hash(key_hash: str) -> dict | None:
    """Look a presented key up by its hash and stamp last-used. None = unknown."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone()
    if not row:
        return None
    with conn:
        conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (_now(), row["id"]))
    return dict(row)


def add_report_blob(
    report_uuid: str,
    *,
    file_unique_id: str,
    saved_filename: str,
    nonce: bytes,
    plaintext_sha256: str,
    ciphertext: bytes = b"",
    cipher_path: str | None = None,
    indicator: bool = False,
) -> int:
    """Insert an image blob. Returns the blob id (existing one if already present).

    Pass ``cipher_path`` (relative to the upload dir) for the normal case: the
    ciphertext sits on disk and only ``nonce`` + hash + path go in the DB.
    ``ciphertext`` is for blobs whose bytes live in the DB — i.e. filed ones.

    ``INSERT OR IGNORE`` + the unique (report_uuid, file_unique_id) index make
    this idempotent — a raced/retried extend can't create duplicate blobs.
    """
    conn = _get_conn()
    with conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO report_blobs
                (report_uuid, file_unique_id, saved_filename, nonce, ciphertext, cipher_path,
                 plaintext_sha256, created_at, indicator)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_uuid,
                file_unique_id,
                saved_filename,
                nonce,
                ciphertext,
                cipher_path,
                plaintext_sha256,
                _now(),
                1 if indicator else 0,
            ),
        )
        if cur.rowcount == 0:  # already there — return the existing blob's id
            row = conn.execute(
                "SELECT id FROM report_blobs WHERE report_uuid = ? AND file_unique_id = ?",
                (report_uuid, file_unique_id),
            ).fetchone()
            return int(row["id"]) if row else 0
    return int(cur.lastrowid or 0)


def set_blob_ciphertext(blob_id: int, ciphertext: bytes) -> None:
    """Move a blob's ciphertext INTO the DB and forget its on-disk path.

    Called on filing: a reported file's encrypted bytes become part of the
    permanent record, so they stop depending on a file that later cleanup (or a
    ban) would delete.
    """
    conn = _get_conn()
    with conn:
        conn.execute(
            "UPDATE report_blobs SET ciphertext = ?, cipher_path = NULL WHERE id = ?",
            (ciphertext, blob_id),
        )


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
    with conn:
        conn.execute(
            "UPDATE report_blobs SET video_path = ?, video_nonce = ?, video_sha256 = ?, video_filename = ? "
            "WHERE id = ?",
            (video_path, video_nonce, video_sha256, video_filename, blob_id),
        )


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
    with conn:
        conn.execute(
            "UPDATE reports SET status = ?, status_detail = ?, updated_at = ? WHERE report_uuid = ?",
            (status, detail, _now(), report_uuid),
        )


def set_report_ncmec_id(report_uuid: str, ncmec_report_id: int) -> None:
    conn = _get_conn()
    with conn:
        conn.execute(
            "UPDATE reports SET ncmec_report_id = ?, updated_at = ? WHERE report_uuid = ?",
            (ncmec_report_id, _now(), report_uuid),
        )


def mark_report_filed(report_uuid: str) -> None:
    conn = _get_conn()
    with conn:
        conn.execute(
            "UPDATE reports SET status = ?, finished_at = ?, updated_at = ? WHERE report_uuid = ?",
            (REPORT_FILED, _now(), _now(), report_uuid),
        )


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
    is ACTUALLY a video/animation (``is_video`` recorded at ingest) — so the
    viewer offers the video from the very first open, not only after a fetch has
    happened. It is NOT inferred from the coarse ``file_type``: a jpg sent as a
    document is not a video. The ciphertext itself (image in DB, video on disk) is
    fetched via the blob endpoints only after the admin supplies P1.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT b.id, b.file_unique_id, b.saved_filename, b.plaintext_sha256, b.selected, "
        "b.classification, b.video_filename, b.indicator, f.is_video, f.original_filename "
        "FROM report_blobs b LEFT JOIN files f ON f.file_unique_id = b.file_unique_id "
        "WHERE b.report_uuid = ? ORDER BY b.id",
        (report_uuid,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["has_video"] = bool(d.get("video_filename")) or bool(d.pop("is_video", 0))
        out.append(d)
    return out


def get_blob_cipher(report_uuid: str, blob_id: int) -> dict | None:
    """Nonce + ciphertext for one blob (for the browser to decrypt)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, nonce, ciphertext, cipher_path FROM report_blobs WHERE report_uuid = ? AND id = ?",
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
    with conn:
        # Reset all to unselected first, then apply the given selections.
        conn.execute(
            "UPDATE report_blobs SET selected = 0, classification = NULL WHERE report_uuid = ?", (report_uuid,)
        )
        for blob_id, classification in selections.items():
            conn.execute(
                "UPDATE report_blobs SET selected = 1, classification = ? WHERE report_uuid = ? AND id = ?",
                (classification, report_uuid, blob_id),
            )


def purge_report_blobs(report_uuid: str) -> int:
    """Delete all encrypted blobs for a report. Returns count deleted."""
    conn = _get_conn()
    with conn:
        cur = conn.execute("DELETE FROM report_blobs WHERE report_uuid = ?", (report_uuid,))
    return cur.rowcount


def purge_unselected_blobs(report_uuid: str) -> int:
    """Delete only the NON-reported (unselected) blobs for a report.

    Used on finish: the reported files' encrypted blobs are KEPT (linked to the
    filed report for later inspection), while the ones the admin did not report
    are removed. Returns count deleted.
    """
    conn = _get_conn()
    with conn:
        cur = conn.execute("DELETE FROM report_blobs WHERE report_uuid = ? AND selected = 0", (report_uuid,))
    return cur.rowcount


def active_report_for_user(user_id: int) -> dict | None:
    """The most recent non-terminal report for a user (preparing/ready/review/submitting)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM reports WHERE user_id = ? AND status IN (?, ?, ?, ?) ORDER BY created_at DESC LIMIT 1",
        (user_id, REPORT_PREPARING, REPORT_READY, REPORT_REVIEW, REPORT_SUBMITTING),
    ).fetchone()
    return dict(row) if row else None


def reports_for_user(user_id: int) -> list[dict]:
    """Every report row for a user, newest first."""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM reports WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def all_reports() -> list[dict]:
    """All reports, newest first — for the admin overview command."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT r.*, u.username, u.first_name, u.last_name FROM reports r "
        "LEFT JOIN users u ON u.user_id = r.user_id ORDER BY r.created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# Report outcomes the statistics dashboard reports on. `filed` went to NCMEC,
# `deleted` destroyed the material without filing — both are real outcomes worth
# counting, and both keep their blobs, so their files stay resolvable.
STATS_STATUSES = (REPORT_FILED, REPORT_DELETED)


def report_stats() -> list[dict]:
    """Per-report records for the statistics dashboard (filed + deleted).

    Cancelled/errored/in-flight reports are excluded — nothing was decided about
    them. Each record carries what the stats view needs to do all its own
    aggregation + period filtering client-side:

      * ``status``        — ``filed`` or ``deleted``, so the view can split them
      * ``user_id``       — for the unique-user count
      * ``language``      — the uploader's Telegram UI language (may be None)
      * ``finished_at``   — when it was decided (drives year/month dropdowns);
                            falls back to ``updated_at`` then ``created_at`` for
                            old rows closed before ``finished_at`` was recorded
      * ``upload_times``  — unix ts of each reported file's ORIGINAL upload, for
                            the weekday×hour "when were they posted" heatmap
      * ``file_types``    — {file_type: count} of the reported files by their
                            ACTUAL recorded Telegram type (photo/video/sticker/
                            gif/document/unknown) — NOT forced into an
                            image/video binary

    One statement, not a report query plus a per-report file query: the whole
    thing joins reports → users → sources → blobs → files and is folded into
    per-report records here. Every blob still attached to the report counts —
    closing a report purges the ones it did not act on, so what remains IS the
    material the decision was about.
    """
    conn = _get_conn()
    placeholders = ",".join("?" * len(STATS_STATUSES))
    try:
        rows = conn.execute(
            "SELECT r.report_uuid, r.status, r.user_id, "
            "COALESCE(r.finished_at, r.updated_at, r.created_at) AS reported_at, "
            "u.language_code AS language, COALESCE(s.name, ?) AS source, "
            "f.file_type, f.upload_time "
            "FROM reports r "
            "LEFT JOIN users u ON u.user_id = r.user_id "
            "LEFT JOIN report_sources s ON s.id = r.source_id "
            "LEFT JOIN report_blobs b ON b.report_uuid = r.report_uuid "
            "LEFT JOIN files f ON f.file_unique_id = b.file_unique_id "
            f"WHERE r.status IN ({placeholders})",
            (DEFAULT_SOURCE, *STATS_STATUSES),
        ).fetchall()
    except sqlite3.OperationalError:
        return []  # reports table not created yet

    # Fold the flat join back into one record per report. A report with no blobs
    # left still yields a row (LEFT JOIN), with NULL file columns.
    out: dict[str, dict] = {}
    for row in rows:
        rec = out.get(row["report_uuid"])
        if rec is None:
            rec = out[row["report_uuid"]] = {
                "status": row["status"],
                "user_id": row["user_id"],
                "language": row["language"],
                "finished_at": row["reported_at"],
                "source": row["source"],
                "upload_times": [],
                "file_types": {},
            }
        if row["file_type"] is None and row["upload_time"] is None:
            continue  # no blob for this report
        if row["upload_time"] is not None:
            rec["upload_times"].append(row["upload_time"])
        # We do NOT infer "video" from capability flags — a sticker is usually a
        # static image and a document can be anything. Missing type → "unknown".
        ftype = row["file_type"] or "unknown"
        rec["file_types"][ftype] = rec["file_types"].get(ftype, 0) + 1
    return list(out.values())
