"""Short-lived store for paged engine results.

Telegram callback data is capped at 64 bytes, far too little to carry a whole
result — so a search stores its candidate list here and only a short token plus
the page index travels in the button.
"""

from __future__ import annotations

from secrets import token_urlsafe
from typing import NamedTuple

from cachetools import TTLCache

from reverse_image_search_bot.engines.types import ProviderMatches

__all__ = ["PagedResult", "get_matches", "store_matches"]


class PagedResult(NamedTuple):
    engine_name: str
    url: str
    matches: ProviderMatches


# Same TTL as the engines' own best-match cache — a token that outlived the
# results it points at would only produce confusing empty pages.
_STORE: TTLCache = TTLCache(maxsize=4096, ttl=24 * 60 * 60)


def store_matches(engine_name: str, url: str, matches: ProviderMatches) -> str:
    """Store a candidate list and return the token to reference it with."""
    token = token_urlsafe(8)
    _STORE[token] = PagedResult(engine_name, url, list(matches))
    return token


def get_matches(token: str) -> PagedResult | None:
    """Get a stored candidate list, or None when it expired / never existed."""
    return _STORE.get(token)
