"""Tests for the incoming per-user search rate limiter."""

import pytest

from reverse_image_search_bot import settings
from reverse_image_search_bot.ratelimit import (
    DEFAULT_LIMITS,
    UNLIMITED,
    SearchLimits,
    SearchRateLimiter,
    limits_for,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def limits():
    return SearchLimits(max_searches=3, window=60.0)


class TestSlidingWindow:
    def test_allows_up_to_max_in_burst(self, clock, limits):
        limiter = SearchRateLimiter(clock=clock)
        for _ in range(limits.max_searches):
            assert limiter.check(1, limits).allowed

    def test_blocks_after_max(self, clock, limits):
        limiter = SearchRateLimiter(clock=clock)
        for _ in range(limits.max_searches):
            limiter.check(1, limits)
        decision = limiter.check(1, limits)
        assert not decision.allowed
        assert decision.retry_after == pytest.approx(60.0)

    def test_window_slides(self, clock, limits):
        limiter = SearchRateLimiter(clock=clock)
        for _ in range(limits.max_searches):
            limiter.check(1, limits)
            clock.advance(10)
        # oldest hit is 30s old; still blocked
        assert not limiter.check(1, limits).allowed
        # after the oldest hit falls out of the window one slot frees up
        clock.advance(31)
        assert limiter.check(1, limits).allowed
        assert not limiter.check(1, limits).allowed

    def test_retry_after_shrinks_over_time(self, clock, limits):
        limiter = SearchRateLimiter(clock=clock)
        for _ in range(limits.max_searches):
            limiter.check(1, limits)
        clock.advance(20)
        assert limiter.check(1, limits).retry_after == pytest.approx(40.0)

    def test_blocked_request_does_not_extend_cooldown(self, clock, limits):
        limiter = SearchRateLimiter(clock=clock)
        for _ in range(limits.max_searches):
            limiter.check(1, limits)
        for _ in range(5):
            limiter.check(1, limits)
        clock.advance(61)
        assert limiter.check(1, limits).allowed

    def test_users_are_independent(self, clock, limits):
        limiter = SearchRateLimiter(clock=clock)
        for _ in range(limits.max_searches):
            limiter.check(1, limits)
        assert not limiter.check(1, limits).allowed
        assert limiter.check(2, limits).allowed


class TestFirstBlock:
    def test_first_block_only_once_per_cooldown(self, clock, limits):
        limiter = SearchRateLimiter(clock=clock)
        for _ in range(limits.max_searches):
            limiter.check(1, limits)
        first = limiter.check(1, limits)
        second = limiter.check(1, limits)
        assert first.first_block is True
        assert second.first_block is False

    def test_first_block_rearms_after_recovery(self, clock, limits):
        limiter = SearchRateLimiter(clock=clock)
        for _ in range(limits.max_searches):
            limiter.check(1, limits)
        assert limiter.check(1, limits).first_block is True
        clock.advance(61)
        assert limiter.check(1, limits).allowed
        for _ in range(limits.max_searches - 1):
            assert limiter.check(1, limits).allowed
        assert limiter.check(1, limits).first_block is True

    def test_allowed_decision_is_not_a_first_block(self, clock, limits):
        limiter = SearchRateLimiter(clock=clock)
        decision = limiter.check(1, limits)
        assert decision.allowed
        assert decision.first_block is False
        assert decision.retry_after == 0.0


class TestUnlimited:
    def test_unlimited_never_blocks(self, clock):
        limiter = SearchRateLimiter(clock=clock)
        for _ in range(100):
            assert limiter.check(1, UNLIMITED).allowed

    def test_zero_max_is_unlimited(self):
        assert SearchLimits(max_searches=0, window=60).unlimited
        assert SearchLimits(max_searches=-1, window=60).unlimited
        assert not SearchLimits(max_searches=1, window=60).unlimited


class TestLimitsFor:
    def test_regular_user_gets_defaults(self):
        assert limits_for(999_999_999) == DEFAULT_LIMITS

    def test_admin_is_exempt(self, monkeypatch):
        monkeypatch.setattr("reverse_image_search_bot.ratelimit.ADMIN_IDS", [4242])
        assert limits_for(4242) is UNLIMITED

    def test_limiter_uses_limits_for_when_none_passed(self, clock, monkeypatch):
        monkeypatch.setattr("reverse_image_search_bot.ratelimit.ADMIN_IDS", [7])
        limiter = SearchRateLimiter(clock=clock)
        for _ in range(50):
            assert limiter.check(7).allowed


class TestReset:
    def test_reset_single_user(self, clock, limits):
        limiter = SearchRateLimiter(clock=clock)
        for _ in range(limits.max_searches):
            limiter.check(1, limits)
        limiter.check(2, limits)
        limiter.reset(1)
        assert limiter.check(1, limits).allowed

    def test_reset_all(self, clock, limits):
        limiter = SearchRateLimiter(clock=clock)
        for _ in range(limits.max_searches):
            limiter.check(1, limits)
        limiter.reset()
        assert limiter.check(1, limits).allowed


class TestSettingsDefaults:
    def test_defaults_are_more_generous_than_the_old_10s_gap(self):
        """Old policy: 1 search per 10s (6/min, no burst)."""
        assert settings.SEARCH_RATE_LIMIT_MAX == 10
        assert settings.SEARCH_RATE_LIMIT_WINDOW == 60.0
        old_rate = 60.0 / 10.0  # searches per minute under the old policy
        new_rate = settings.SEARCH_RATE_LIMIT_MAX / (settings.SEARCH_RATE_LIMIT_WINDOW / 60.0)
        assert new_rate > old_rate

    def test_default_limits_come_from_settings(self):
        assert DEFAULT_LIMITS.max_searches == settings.SEARCH_RATE_LIMIT_MAX
        assert DEFAULT_LIMITS.window == settings.SEARCH_RATE_LIMIT_WINDOW
