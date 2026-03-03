"""Tests for reverse_image_search_bot.engines.errors."""

from reverse_image_search_bot.engines.errors import EngineError, RateLimitError, SearchError


class TestErrorHierarchy:
    def test_search_error_is_engine_error(self):
        assert issubclass(SearchError, EngineError)

    def test_rate_limit_is_engine_error(self):
        assert issubclass(RateLimitError, EngineError)

    def test_engine_error_is_exception(self):
        assert issubclass(EngineError, Exception)


class TestRateLimitError:
    def test_default_attrs(self):
        err = RateLimitError()
        assert str(err) == "Rate limit reached"
        assert err.period == ""
        assert err.retry_after is None

    def test_custom_attrs(self):
        err = RateLimitError("SauceNAO limit", period="Daily", retry_after=3600)
        assert str(err) == "SauceNAO limit"
        assert err.period == "Daily"
        assert err.retry_after == 3600

    def test_catchable_as_engine_error(self):
        try:
            raise RateLimitError("test", period="Monthly")
        except EngineError as e:
            assert isinstance(e, RateLimitError)
            assert e.period == "Monthly"


class TestSearchError:
    def test_message(self):
        err = SearchError("Parsing key missing: 'trace_id'")
        assert "trace_id" in str(err)
