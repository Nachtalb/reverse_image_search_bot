"""Persistent best-match result cache.

Engine best-match lookups used to live in a process-local ``TTLCache``, so every
restart or redeploy threw the lot away and the next searches re-spent SauceNAO /
trace.moe / Google Vision quota on images already looked up. The cache now lives
in the config DB and survives restarts.

Operational cache, not evidence — it deliberately sits in ``config.db`` and not
in ``abuse.db`` so it can be dropped at any time without touching report data.
"""

from __future__ import annotations

import json
import logging
import time
from functools import wraps
from typing import Any

from telegram import InlineKeyboardButton
from yarl import URL

from reverse_image_search_bot import settings
from reverse_image_search_bot.config.db import connection

logger = logging.getLogger(__name__)

_URL_TAG = "__url__"
_SET_TAG = "__set__"
_BUTTON_TAG = "__btn__"


def is_empty(payload: tuple[dict, dict]) -> bool:
    """A search that found nothing: no result fields and no metadata."""
    result, meta = payload
    return not result and not meta


def ttl_seconds(payload: tuple[dict, dict] | None = None) -> int:
    """Lifetime for a payload.

    A hit is stable — the engine matched something and will keep matching it.
    A *miss* is not: the engines index new images continuously, so an image with
    no match today may well have one next week. Caching "nothing found" for the
    full period would keep answering from a stale negative for weeks, so misses
    expire far sooner.
    """
    if payload is not None and is_empty(payload):
        return settings.RESULT_CACHE_EMPTY_TTL_HOURS * 3600
    return settings.RESULT_CACHE_TTL_DAYS * 86400


# --- codec --------------------------------------------------------------------
# ProviderData carries yarl.URL, set[str] and InlineKeyboardButton — none of them
# JSON-native — so each is stored as a single-key tagged object.


def _enc(value: Any) -> Any:
    if isinstance(value, URL):
        return {_URL_TAG: str(value)}
    if isinstance(value, InlineKeyboardButton):
        return {_BUTTON_TAG: value.to_dict()}
    if isinstance(value, set):
        return {_SET_TAG: sorted(_enc(v) for v in value)}
    if isinstance(value, list | tuple):
        return [_enc(v) for v in value]
    if isinstance(value, dict):
        return {k: _enc(v) for k, v in value.items()}
    return value


def _dec(value: Any) -> Any:
    if isinstance(value, dict):
        if len(value) == 1:
            if _URL_TAG in value:
                return URL(value[_URL_TAG])
            if _BUTTON_TAG in value:
                return InlineKeyboardButton.de_json(value[_BUTTON_TAG])
            if _SET_TAG in value:
                return {_dec(v) for v in value[_SET_TAG]}
        return {k: _dec(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dec(v) for v in value]
    return value


def encode(payload: tuple[dict, dict]) -> str:
    result, meta = payload
    return json.dumps([_enc(result), _enc(meta)])


def decode(raw: str) -> tuple[dict, dict]:
    result, meta = json.loads(raw)
    return _dec(result), _dec(meta)


# --- store --------------------------------------------------------------------


def get(engine: str, image_url: str, now: float | None = None) -> tuple[dict, dict] | None:
    """Return the cached payload for this engine+url, or None on miss/expiry.

    A row that will not decode is treated as a miss and dropped: the caller then
    does a live search, which is the correct degradation.
    """
    stamp = int(now if now is not None else time.time())
    row = (
        connection()
        .execute(
            "SELECT payload FROM best_match_cache WHERE engine = ? AND image_url = ? AND expires_at > ?",
            (engine, image_url, stamp),
        )
        .fetchone()
    )
    if row is None:
        return None
    try:
        return decode(row["payload"])
    except ValueError, TypeError, KeyError:
        # Not a warning: WARNING+ records are delivered to Telegram admins.
        logger.info("result cache: dropping undecodable row for %s %s", engine, image_url, exc_info=True)
        conn = connection()
        conn.execute("DELETE FROM best_match_cache WHERE engine = ? AND image_url = ?", (engine, image_url))
        conn.commit()
        return None


def put(engine: str, image_url: str, payload: tuple[dict, dict], now: float | None = None) -> None:
    """Store a payload with the expiry its own kind earns (see ``ttl_seconds``)."""
    stamp = int(now if now is not None else time.time())
    conn = connection()
    conn.execute(
        "INSERT INTO best_match_cache (engine, image_url, payload, created_at, expires_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(engine, image_url) DO UPDATE SET payload = excluded.payload, "
        "created_at = excluded.created_at, expires_at = excluded.expires_at",
        (engine, image_url, encode(payload), stamp, stamp + ttl_seconds(payload)),
    )
    conn.commit()


def clear() -> None:
    """Drop every cached entry. Test hook and manual escape hatch."""
    conn = connection()
    conn.execute("DELETE FROM best_match_cache")
    conn.commit()


def sweep(now: float | None = None) -> int:
    """Delete expired rows. Called by the daily retention job."""
    stamp = int(now if now is not None else time.time())
    conn = connection()
    removed = conn.execute("DELETE FROM best_match_cache WHERE expires_at <= ?", (stamp,)).rowcount
    conn.commit()
    return removed


# --- decorator ----------------------------------------------------------------


def cached_best_match(func):
    """Cache an engine's ``best_match`` by (engine name, image url).

    Keyed on the engine's *name* rather than the instance: engine objects are
    rebuilt on every start, so an identity-based key would never hit across
    restarts. Cache faults never propagate — the search runs live instead.
    """

    @wraps(func)
    async def wrapper(self, url, *args, **kwargs):
        key = str(url)
        try:
            hit = get(self.name, key)
        except Exception:
            logger.info("result cache: read failed for %s", self.name, exc_info=True)
            hit = None
        if hit is not None:
            return hit
        payload = await func(self, url, *args, **kwargs)
        try:
            put(self.name, key, payload)
        except Exception:
            logger.info("result cache: write failed for %s", self.name, exc_info=True)
        return payload

    return wrapper
