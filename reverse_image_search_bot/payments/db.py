"""SQLite tables for subscriptions and daily/monthly usage tracking.

Uses the same database file and thread-local connection pattern as config/db.py.
"""

import atexit
import contextlib
import sqlite3
import threading
from datetime import UTC, datetime, timedelta

from reverse_image_search_bot.settings import CONFIG_DB_PATH

_local = threading.local()
_all_connections: list[sqlite3.Connection] = []
_conn_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    """Get a thread-local SQLite connection with WAL mode."""
    if not hasattr(_local, "pay_conn") or _local.pay_conn is None:
        CONFIG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(CONFIG_DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        _ensure_schema(conn)
        with _conn_lock:
            _all_connections.append(conn)
        _local.pay_conn = conn
    return _local.pay_conn


def _close_all_connections():
    with _conn_lock:
        for conn in _all_connections:
            with contextlib.suppress(Exception):
                conn.close()
        _all_connections.clear()


atexit.register(_close_all_connections)


def _ensure_schema(conn: sqlite3.Connection):
    """Create subscription and usage tables if they don't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            subscription_start TEXT NOT NULL,
            subscription_end TEXT NOT NULL,
            transaction_id TEXT NOT NULL UNIQUE,
            stars_amount INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_subscriptions_chat_id
        ON subscriptions (chat_id)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_usage (
            chat_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            search_count INTEGER NOT NULL DEFAULT 0,
            google_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monthly_usage (
            chat_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            search_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, month)
        )
    """)
    # Migration: add google_count column if missing (from old schema)
    try:
        conn.execute("ALTER TABLE daily_usage ADD COLUMN google_count INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e):
            raise
    conn.commit()


# ── Subscriptions ────────────────────────────────────────────────────────


def add_subscription(chat_id: int, days: int, transaction_id: str, stars_amount: int) -> None:
    """Record a new subscription period for a chat."""
    conn = _get_conn()
    now = datetime.now(UTC)
    # Extend from current subscription end if still active
    row = conn.execute(
        "SELECT subscription_end FROM subscriptions WHERE chat_id = ? ORDER BY subscription_end DESC LIMIT 1",
        (chat_id,),
    ).fetchone()
    if row:
        existing_end = datetime.fromisoformat(row["subscription_end"])
        if existing_end > now:
            now = existing_end

    end = now + timedelta(days=days)
    conn.execute(
        "INSERT INTO subscriptions (chat_id, subscription_start, subscription_end, transaction_id, stars_amount) "
        "VALUES (?, ?, ?, ?, ?)",
        (chat_id, now.isoformat(), end.isoformat(), transaction_id, stars_amount),
    )
    conn.commit()


def get_active_subscription(chat_id: int) -> dict | None:
    """Return the active subscription for a chat, or None."""
    conn = _get_conn()
    now = datetime.now(UTC).isoformat()
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE chat_id = ? AND subscription_end > ? ORDER BY subscription_end DESC LIMIT 1",
        (chat_id, now),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_all_subscriptions() -> list[dict]:
    """Return all subscriptions ordered by start date descending.

    Each dict includes 'refunded' and 'active' booleans.
    """
    conn = _get_conn()
    now = datetime.now(UTC).isoformat()
    rows = conn.execute("SELECT * FROM subscriptions ORDER BY subscription_start DESC").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        start = datetime.fromisoformat(d["subscription_start"])
        end = datetime.fromisoformat(d["subscription_end"])
        d["refunded"] = (end - start).days < 1
        d["active"] = d["subscription_end"] > now and not d["refunded"]
        result.append(d)
    return result


def revoke_subscription(chat_id: int, transaction_id: str) -> bool:
    """Revoke a subscription by setting its end date to now. Returns True if a row was updated."""
    conn = _get_conn()
    now = datetime.now(UTC).isoformat()
    cursor = conn.execute(
        "UPDATE subscriptions SET subscription_end = ? WHERE chat_id = ? AND transaction_id = ?",
        (now, chat_id, transaction_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def count_premium_chats() -> int:
    """Count chats with an active subscription."""
    conn = _get_conn()
    now = datetime.now(UTC).isoformat()
    row = conn.execute(
        "SELECT COUNT(DISTINCT chat_id) as cnt FROM subscriptions WHERE subscription_end > ?",
        (now,),
    ).fetchone()
    return row["cnt"] if row else 0


# ── Usage Tracking ───────────────────────────────────────────────────────


def get_usage(chat_id: int) -> tuple[int, int, int]:
    """Return (daily_searches, monthly_searches, google_daily) for a chat."""
    conn = _get_conn()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    month = datetime.now(UTC).strftime("%Y-%m")

    daily_row = conn.execute(
        "SELECT search_count, google_count FROM daily_usage WHERE chat_id = ? AND date = ?",
        (chat_id, today),
    ).fetchone()
    daily = daily_row["search_count"] if daily_row else 0
    google = daily_row["google_count"] if daily_row else 0

    monthly_row = conn.execute(
        "SELECT search_count FROM monthly_usage WHERE chat_id = ? AND month = ?",
        (chat_id, month),
    ).fetchone()
    monthly = monthly_row["search_count"] if monthly_row else 0

    return daily, monthly, google


def increment_usage(chat_id: int, is_google: bool = False) -> None:
    """Increment daily and monthly usage counters for a chat."""
    conn = _get_conn()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    month = datetime.now(UTC).strftime("%Y-%m")
    google_inc = 1 if is_google else 0

    conn.execute(
        "INSERT INTO daily_usage (chat_id, date, search_count, google_count) VALUES (?, ?, 1, ?) "
        "ON CONFLICT(chat_id, date) DO UPDATE SET search_count = search_count + 1, "
        "google_count = google_count + ?",
        (chat_id, today, google_inc, google_inc),
    )
    conn.execute(
        "INSERT INTO monthly_usage (chat_id, month, search_count) VALUES (?, ?, 1) "
        "ON CONFLICT(chat_id, month) DO UPDATE SET search_count = search_count + 1",
        (chat_id, month),
    )
    conn.commit()


def reset_daily_usage() -> int:
    """Delete all daily usage rows (called at midnight UTC). Returns rows deleted."""
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM daily_usage")
    conn.commit()
    return cursor.rowcount


def reset_monthly_usage() -> int:
    """Delete all monthly usage rows (called on 1st of month). Returns rows deleted."""
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM monthly_usage")
    conn.commit()
    return cursor.rowcount
