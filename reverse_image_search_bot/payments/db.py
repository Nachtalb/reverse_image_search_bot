"""SQLite tables for subscriptions and daily usage tracking.

Uses the same database file and thread-local connection pattern as config/db.py.
"""

import atexit
import contextlib
import sqlite3
import threading
from datetime import UTC, datetime

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
            saucenao_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, date)
        )
    """)
    conn.commit()


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

    from datetime import timedelta

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


def get_daily_usage(chat_id: int) -> tuple[int, int]:
    """Return (search_count, saucenao_count) for today."""
    conn = _get_conn()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT search_count, saucenao_count FROM daily_usage WHERE chat_id = ? AND date = ?",
        (chat_id, today),
    ).fetchone()
    if row is None:
        return 0, 0
    return row["search_count"], row["saucenao_count"]


def increment_usage(chat_id: int, is_saucenao: bool = False) -> None:
    """Increment daily usage counters for a chat."""
    conn = _get_conn()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    saucenao_inc = 1 if is_saucenao else 0
    conn.execute(
        "INSERT INTO daily_usage (chat_id, date, search_count, saucenao_count) VALUES (?, ?, 1, ?) "
        "ON CONFLICT(chat_id, date) DO UPDATE SET search_count = search_count + 1, "
        "saucenao_count = saucenao_count + ?",
        (chat_id, today, saucenao_inc, saucenao_inc),
    )
    conn.commit()


def reset_all_daily_usage() -> int:
    """Delete all daily usage rows (called at midnight UTC). Returns rows deleted."""
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM daily_usage")
    conn.commit()
    return cursor.rowcount


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
