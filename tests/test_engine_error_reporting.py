"""Tests for error-tracking noise triage (transient detection, report flags)."""

import httpx
import pytest

from reverse_image_search_bot.engines.errors import SearchError, is_transient


def test_chained_timeout_is_transient():
    with pytest.raises(SearchError) as exc_info:
        try:
            raise httpx.ConnectTimeout("")
        except Exception as e:
            raise SearchError("Search failed: ConnectTimeout") from e
    assert is_transient(exc_info.value)


def test_http_5xx_is_not_transient():
    assert not is_transient(SearchError("SauceNAO returned HTTP 500"))


def test_oserror_is_not_transient():
    # ffmpeg / file I/O errors are real bugs, must stay reported
    assert not is_transient(OSError("ffmpeg boom"))


def test_search_error_report_flag():
    assert SearchError("x").report is True
    assert SearchError("x", report=False).report is False


def test_yandex_parsing_reporting_disabled():
    from reverse_image_search_bot.engines.yandex import YandexEngine

    assert YandexEngine.report_parsing_errors is False


@pytest.mark.asyncio
async def test_json_decode_from_provider_is_not_reported(monkeypatch):
    """An empty/non-JSON provider body (JSONDecodeError) must be caught as a
    non-reported SearchError, not shipped to error tracking as a bug."""
    import json

    from reverse_image_search_bot.engines.yandex import YandexEngine

    engine = YandexEngine()

    async def _boom(_url):
        json.loads("")  # raises JSONDecodeError

    monkeypatch.setattr(engine, "_search", _boom)

    with pytest.raises(SearchError) as exc_info:
        await engine.best_match("https://example.com/x.jpg")
    assert exc_info.value.report is False
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)
