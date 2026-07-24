"""Tests for reverse_image_search_bot.engines.google — mocked HTTP."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from reverse_image_search_bot import settings
from reverse_image_search_bot.engines.errors import RateLimitError, SearchError
from reverse_image_search_bot.engines.google import GoogleEngine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_VISION_API", "test-key")
    monkeypatch.setattr(settings, "GOOGLE_VISION_QUOTA_PATH", tmp_path / "quota.json")
    monkeypatch.setattr(settings, "GOOGLE_VISION_MONTHLY_LIMIT", 1000)
    e = GoogleEngine()
    e._best_match_cache.clear()
    return e


def _vision_response(full=True, partial=False, pages=True):
    web = {
        "webEntities": [{"description": "Line art", "score": 0.9}],
        "bestGuessLabels": [{"label": "line art"}],
    }
    if full:
        web["fullMatchingImages"] = [{"url": "https://example.com/full.jpg"}]
    if partial:
        web["partialMatchingImages"] = [{"url": "https://example.com/partial.jpg"}]
    if pages:
        web["pagesWithMatchingImages"] = [
            {"url": "https://example.com/page", "pageTitle": "Some page"},
        ]
    return {"responses": [{"webDetection": web}]}


def _mock_resp(status_code=200, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload if payload is not None else _vision_response()
    return resp


@pytest.mark.asyncio
class TestGoogleBestMatch:
    async def test_finds_match(self, engine):
        with patch.object(engine._http_client, "post", new_callable=AsyncMock, return_value=_mock_resp()):
            result, meta = await engine.best_match("https://example.com/img.jpg")
        assert result["Best guess"] == "line art"
        assert result["Match"] == "Full"
        assert meta["provider"] == "Google"
        assert meta["buttons"]
        assert "thumbnail" in meta

    async def test_no_results(self, engine):
        payload = {"responses": [{"webDetection": {}}]}
        with patch.object(
            engine._http_client, "post", new_callable=AsyncMock, return_value=_mock_resp(payload=payload)
        ):
            result, meta = await engine.best_match("https://example.com/none.jpg")
        assert result == {}
        assert meta == {}

    async def test_partial_only(self, engine):
        payload = _vision_response(full=False, partial=True, pages=False)
        with patch.object(
            engine._http_client, "post", new_callable=AsyncMock, return_value=_mock_resp(payload=payload)
        ):
            result, _ = await engine.best_match("https://example.com/partial.jpg")
        assert result["Match"] == "Partial"

    async def test_http_error_raises_search_error(self, engine):
        with (
            patch.object(engine._http_client, "post", new_callable=AsyncMock, return_value=_mock_resp(403, {})),
            pytest.raises(SearchError),
        ):
            await engine.best_match("https://example.com/err.jpg")

    async def test_429_raises_rate_limit(self, engine):
        with (
            patch.object(engine._http_client, "post", new_callable=AsyncMock, return_value=_mock_resp(429, {})),
            pytest.raises(RateLimitError),
        ):
            await engine.best_match("https://example.com/429.jpg")

    async def test_quota_exhausted_raises_rate_limit(self, engine, monkeypatch):
        monkeypatch.setattr(settings, "GOOGLE_VISION_MONTHLY_LIMIT", 0)
        with pytest.raises(RateLimitError):
            await engine.best_match("https://example.com/quota.jpg")

    async def test_no_api_key_returns_empty(self, engine, monkeypatch):
        monkeypatch.setattr(settings, "GOOGLE_VISION_API", None)
        result, meta = await engine.best_match("https://example.com/nokey.jpg")
        assert result == {}
        assert meta == {}


class TestQuota:
    def test_counter_increments_and_persists(self, engine):
        assert engine._take_quota()
        assert engine._take_quota()
        data = json.loads(settings.GOOGLE_VISION_QUOTA_PATH.read_text())
        assert data["count"] == 2

    def test_limit_enforced(self, engine, monkeypatch):
        monkeypatch.setattr(settings, "GOOGLE_VISION_MONTHLY_LIMIT", 2)
        assert engine._take_quota()
        assert engine._take_quota()
        assert not engine._take_quota()

    def test_month_rollover_resets(self, engine):
        settings.GOOGLE_VISION_QUOTA_PATH.write_text(json.dumps({"month": "1999-01", "count": 999999}))
        assert engine._take_quota()
        data = json.loads(settings.GOOGLE_VISION_QUOTA_PATH.read_text())
        assert data["count"] == 1

    def test_corrupt_file_recovers(self, engine):
        settings.GOOGLE_VISION_QUOTA_PATH.write_text("not json")
        assert engine._take_quota()

    def test_best_match_implemented_follows_key(self, engine, monkeypatch):
        assert GoogleEngine.best_match_implemented
        monkeypatch.setattr(settings, "GOOGLE_VISION_API", None)
        assert not GoogleEngine.best_match_implemented
