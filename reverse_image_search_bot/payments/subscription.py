"""Subscription logic — premium checks, quota enforcement, and daily resets."""

from __future__ import annotations

import logging
import threading

from cachetools import TTLCache

from reverse_image_search_bot.settings import ADMIN_IDS, DAILY_SAUCENAO_LIMIT, DAILY_SEARCH_LIMIT

from . import db

logger = logging.getLogger(__name__)

# In-memory cache: chat_id → bool (premium status), TTL 5 minutes
_premium_cache: TTLCache[int, bool] = TTLCache(maxsize=4096, ttl=300)
_cache_lock = threading.Lock()


def is_premium(chat_id: int) -> bool:
    """Check if a chat has an active premium subscription.

    Admins are always treated as premium.
    """
    if chat_id in ADMIN_IDS:
        return True

    with _cache_lock:
        cached = _premium_cache.get(chat_id)
        if cached is not None:
            return cached

    result = db.get_active_subscription(chat_id) is not None
    with _cache_lock:
        _premium_cache[chat_id] = result
    return result


def invalidate_premium_cache(chat_id: int) -> None:
    """Remove a chat from the premium cache (e.g. after payment)."""
    with _cache_lock:
        _premium_cache.pop(chat_id, None)


def get_remaining_searches(chat_id: int) -> tuple[int, int]:
    """Return (remaining, daily_limit) for a chat.

    Premium chats get (-1, -1) meaning unlimited.
    """
    if is_premium(chat_id):
        return -1, -1
    used, _ = db.get_daily_usage(chat_id)
    remaining = max(0, DAILY_SEARCH_LIMIT - used)
    return remaining, DAILY_SEARCH_LIMIT


def get_remaining_saucenao(chat_id: int) -> int:
    """Return remaining SauceNAO searches for today. -1 if premium."""
    if is_premium(chat_id):
        return -1
    _, saucenao_used = db.get_daily_usage(chat_id)
    return max(0, DAILY_SAUCENAO_LIMIT - saucenao_used)


def use_search(chat_id: int, engine_name: str) -> bool:
    """Try to consume a search quota. Returns True if allowed, False if limit hit.

    For premium users, always returns True without incrementing.
    """
    if is_premium(chat_id):
        return True

    is_saucenao = engine_name.lower() == "saucenao"
    used, saucenao_used = db.get_daily_usage(chat_id)

    # Check daily global limit
    if used >= DAILY_SEARCH_LIMIT:
        return False

    # Check SauceNAO-specific limit
    if is_saucenao and saucenao_used >= DAILY_SAUCENAO_LIMIT:
        return False

    db.increment_usage(chat_id, is_saucenao=is_saucenao)
    return True


def reset_daily_counts() -> None:
    """Reset all daily usage counters. Called by the midnight UTC job."""
    deleted = db.reset_all_daily_usage()
    logger.info("Reset daily usage counters (%d rows cleared)", deleted)
