"""Subscription logic — premium checks, quota enforcement, and daily resets."""

from __future__ import annotations

import logging
import threading

from cachetools import TTLCache

from reverse_image_search_bot.settings import (
    ADMIN_IDS,
    FREE_DAILY_LIMIT,
    FREE_MONTHLY_LIMIT,
    PREMIUM_DAILY_LIMIT,
    PREMIUM_GOOGLE_DAILY_LIMIT,
)

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


def get_quota_info(chat_id: int) -> dict:
    """Return quota info for a chat.

    Returns dict with keys:
        premium: bool
        daily_remaining: int (-1 = unlimited)
        daily_limit: int
        monthly_remaining: int (-1 = unlimited)
        monthly_limit: int
        google_daily_remaining: int (-1 = not available / unlimited)
        google_daily_limit: int
    """
    premium = is_premium(chat_id)
    daily_used, monthly_used, google_used = db.get_usage(chat_id)

    if premium:
        return {
            "premium": True,
            "daily_remaining": max(0, PREMIUM_DAILY_LIMIT - daily_used),
            "daily_limit": PREMIUM_DAILY_LIMIT,
            "monthly_remaining": -1,
            "monthly_limit": -1,
            "google_daily_remaining": max(0, PREMIUM_GOOGLE_DAILY_LIMIT - google_used),
            "google_daily_limit": PREMIUM_GOOGLE_DAILY_LIMIT,
        }
    else:
        return {
            "premium": False,
            "daily_remaining": max(0, FREE_DAILY_LIMIT - daily_used),
            "daily_limit": FREE_DAILY_LIMIT,
            "monthly_remaining": max(0, FREE_MONTHLY_LIMIT - monthly_used),
            "monthly_limit": FREE_MONTHLY_LIMIT,
            "google_daily_remaining": 0,  # Not available for free
            "google_daily_limit": 0,
        }


def use_search(chat_id: int, engine_name: str) -> tuple[bool, str]:
    """Try to consume a search quota.

    Returns (allowed: bool, reason: str).
    reason is empty if allowed, otherwise a key like 'daily', 'monthly', 'google', 'groups'.
    """
    premium = is_premium(chat_id)
    is_google = "google" in engine_name.lower()

    # Free tier: private chat only (negative chat_ids are groups)
    if not premium and chat_id < 0:
        return False, "groups"

    # Google: premium only
    if is_google and not premium:
        return False, "premium_engine"

    daily_used, monthly_used, google_used = db.get_usage(chat_id)

    if premium:
        # Premium daily limit
        if daily_used >= PREMIUM_DAILY_LIMIT:
            return False, "daily"
        # Google daily limit
        if is_google and google_used >= PREMIUM_GOOGLE_DAILY_LIMIT:
            return False, "google"
    else:
        # Free daily limit
        if daily_used >= FREE_DAILY_LIMIT:
            return False, "daily"
        # Free monthly limit
        if monthly_used >= FREE_MONTHLY_LIMIT:
            return False, "monthly"

    db.increment_usage(chat_id, is_google=is_google)
    return True, ""


def reset_daily_counts() -> None:
    """Reset all daily usage counters. Called by the midnight UTC job."""
    deleted = db.reset_daily_usage()
    logger.info("Reset daily usage counters (%d rows cleared)", deleted)


def reset_monthly_counts() -> None:
    """Reset all monthly usage counters. Called on the 1st of each month."""
    deleted = db.reset_monthly_usage()
    logger.info("Reset monthly usage counters (%d rows cleared)", deleted)
