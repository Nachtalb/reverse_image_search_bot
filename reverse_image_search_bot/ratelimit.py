"""Per-user throttling of INCOMING search requests.

This is the limit the bot imposes on its own users. It has nothing to do with
:class:`telegram.ext.AIORateLimiter`, which throttles our OUTGOING calls to
Telegram's API (and must stay strict), nor with engine-side quota exhaustion
(SauceNAO daily limit, trace.moe 402) which surfaces as
:class:`~reverse_image_search_bot.engines.errors.RateLimitError`.

The policy is a sliding window: a user may run ``max_searches`` searches in any
``window`` seconds. That allows a burst (sending a handful of images at once)
instead of the old fixed minimum gap between searches.

Limits are looked up per user through :func:`limits_for`, so a future paid tier
can return a different :class:`SearchLimits` for a subscriber without touching
any call site. No tier system exists yet — deliberately.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

from .settings import ADMIN_IDS, SEARCH_RATE_LIMIT_MAX, SEARCH_RATE_LIMIT_WINDOW


@dataclass(frozen=True, slots=True)
class SearchLimits:
    """How many searches a user may run in a sliding window.

    ``max_searches <= 0`` means unlimited.
    """

    max_searches: int
    window: float

    @property
    def unlimited(self) -> bool:
        return self.max_searches <= 0


#: Limits applied to ordinary users. Env-var driven, see settings.py.
DEFAULT_LIMITS = SearchLimits(max_searches=SEARCH_RATE_LIMIT_MAX, window=SEARCH_RATE_LIMIT_WINDOW)

#: No throttling at all (admins today, paid tiers later).
UNLIMITED = SearchLimits(max_searches=0, window=0.0)


def limits_for(user_id: int) -> SearchLimits:
    """Return the search limits that apply to ``user_id``.

    Single lookup point: a per-tier/per-plan resolution slots in here later.
    """
    if user_id in ADMIN_IDS:
        return UNLIMITED
    return DEFAULT_LIMITS


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Outcome of a single :meth:`SearchRateLimiter.check` call."""

    allowed: bool
    #: Seconds until the next search would be allowed (0 when allowed).
    retry_after: float = 0.0
    #: True only on the request that first tripped the limit, so callers can log
    #: / notify once per cooldown instead of on every blocked request.
    first_block: bool = False


class SearchRateLimiter:
    """Sliding-window search limiter keyed by user id."""

    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._hits: defaultdict[int, deque[float]] = defaultdict(deque)
        self._blocked: set[int] = set()

    def _prune(self, user_id: int, now: float, window: float) -> deque[float]:
        hits = self._hits[user_id]
        cutoff = now - window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def check(self, user_id: int, limits: SearchLimits | None = None) -> RateLimitDecision:
        """Consume one search slot for ``user_id`` if one is available."""
        limits = limits_for(user_id) if limits is None else limits
        if limits.unlimited:
            self._blocked.discard(user_id)
            return RateLimitDecision(allowed=True)

        now = self._clock()
        hits = self._prune(user_id, now, limits.window)

        if len(hits) >= limits.max_searches:
            retry_after = max(0.0, hits[0] + limits.window - now)
            first_block = user_id not in self._blocked
            self._blocked.add(user_id)
            return RateLimitDecision(allowed=False, retry_after=retry_after, first_block=first_block)

        hits.append(now)
        self._blocked.discard(user_id)
        return RateLimitDecision(allowed=True)

    def reset(self, user_id: int | None = None) -> None:
        """Forget recorded searches (all users, or just one)."""
        if user_id is None:
            self._hits.clear()
            self._blocked.clear()
        else:
            self._hits.pop(user_id, None)
            self._blocked.discard(user_id)


#: Process-wide limiter used by the search command.
search_limiter = SearchRateLimiter()
