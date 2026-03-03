"""Tests for reverse_image_search_bot.engines.saucenao — mocked HTTP."""

from time import time
from unittest.mock import AsyncMock, patch

import pytest

from reverse_image_search_bot.engines.errors import RateLimitError, SearchError
from reverse_image_search_bot.engines.saucenao import SauceNaoEngine


@pytest.fixture
def engine():
    e = SauceNaoEngine()
    e._best_match_cache.clear()
    return e


def _mock_response(status_code=200, json_data=None):
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


@pytest.mark.asyncio
class TestSauceNaoBestMatch:
    async def test_no_results(self, engine):
        mock_resp = _mock_response(200, {"results": []})
        with patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, meta = await engine.best_match("https://example.com/img.jpg")
            assert result == {}
            assert meta == {}

    async def test_non_200_returns_empty(self, engine):
        mock_resp = _mock_response(500)
        with patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, _meta = await engine.best_match("https://example.com/img2.jpg")
            assert result == {}

    async def test_429_raises_rate_limit(self, engine):
        engine.limit_reached = None
        mock_resp = _mock_response(429)
        with (
            patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp),
            pytest.raises(RateLimitError, match="429"),
        ):
            await engine.best_match("https://example.com/img3.jpg")
        assert engine.limit_reached is not None

    async def test_rate_limit_cached(self, engine):
        engine.limit_reached = time()  # just now
        with pytest.raises(RateLimitError, match="daily"):
            await engine.best_match("https://example.com/img4.jpg")

    async def test_below_similarity_filtered(self, engine):
        mock_resp = _mock_response(
            200,
            {
                "results": [
                    {
                        "header": {"similarity": "30.0", "index_id": 99, "thumbnail": "https://t.com/t.jpg"},
                        "data": {"title": "Low match"},
                    }
                ]
            },
        )
        with patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, _meta = await engine.best_match("https://example.com/img5.jpg")
            assert result == {}

    async def test_priority_ordering(self, engine):
        """Index 21 (anilist) should be preferred over index 99 (unknown)."""
        mock_resp = _mock_response(
            200,
            {
                "results": [
                    {
                        "header": {"similarity": "90.0", "index_id": 99, "thumbnail": "https://t.com/a.jpg"},
                        "data": {"title": "Generic", "ext_urls": ["https://example.com"]},
                    },
                    {
                        "header": {"similarity": "85.0", "index_id": 21, "thumbnail": "https://t.com/b.jpg"},
                        "data": {"anilist_id": 12345, "part": 1},
                    },
                ]
            },
        )

        mock_anilist = AsyncMock(return_value=({"Title": "Anime Result"}, {"provided_via": "Anilist"}))

        with (
            patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp),
            patch("reverse_image_search_bot.engines.saucenao.anilist.provide", mock_anilist),
        ):
            result, _meta = await engine.best_match("https://example.com/img6.jpg")
            assert result.get("Title") == "Anime Result"

    async def test_connect_error_raises_search_error(self, engine):
        import httpx

        with (
            patch.object(
                engine._http_client,
                "get",
                new_callable=AsyncMock,
                side_effect=httpx.ConnectError("Connection refused"),
            ),
            pytest.raises(SearchError, match="connecting"),
        ):
            await engine.best_match("https://example.com/img7.jpg")
