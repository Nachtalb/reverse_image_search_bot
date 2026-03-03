"""Tests for reverse_image_search_bot.engines.saucenao — mocked HTTP."""

from time import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from reverse_image_search_bot.engines.errors import RateLimitError, SearchError
from reverse_image_search_bot.engines.saucenao import SauceNaoEngine


@pytest.fixture
def engine():
    e = SauceNaoEngine()
    e._best_match_cache.clear()
    return e


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


def _make_result(index_id, similarity="90.0", data=None):
    """Helper to build a SauceNAO result entry."""
    return {
        "header": {
            "similarity": similarity,
            "index_id": index_id,
            "thumbnail": f"https://img.saucenao.com/thumb_{index_id}.jpg",
        },
        "data": data or {},
    }


@pytest.mark.asyncio
class TestSauceNaoBestMatch:
    async def test_no_results(self, engine):
        mock_resp = _mock_response(200, {"results": []})
        with patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, meta = await engine.best_match("https://example.com/img.jpg")
            assert result == {}
            assert meta == {}

    async def test_non_200_raises_search_error(self, engine):
        mock_resp = _mock_response(500)
        with (
            patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp),
            pytest.raises(SearchError, match="HTTP 500"),
        ):
            await engine.best_match("https://example.com/img2.jpg")

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
            {"results": [_make_result(99, similarity="30.0", data={"title": "Low match"})]},
        )
        with patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, _meta = await engine.best_match("https://example.com/img5.jpg")
            assert result == {}

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


@pytest.mark.asyncio
class TestSauceNaoProviderRouting:
    """Test that specific index_ids route to the correct provider methods."""

    async def test_index_21_calls_anilist(self, engine):
        """Index 21 = anime → _21_provider (anilist)."""
        mock_resp = _mock_response(
            200,
            {"results": [_make_result(21, data={"anilist_id": 12345, "part": 1})]},
        )
        mock_anilist = AsyncMock(return_value=({"Title": "Attack on Titan"}, {"provided_via": "Anilist"}))

        with (
            patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp),
            patch("reverse_image_search_bot.engines.saucenao.anilist.provide", mock_anilist),
        ):
            result, _meta = await engine.best_match("https://example.com/idx21.jpg")
            assert result.get("Title") == "Attack on Titan"
            mock_anilist.assert_awaited_once_with(12345, 1)

    async def test_index_5_calls_pixiv(self, engine):
        """Index 5 = pixiv → _5_provider."""
        mock_resp = _mock_response(
            200,
            {
                "results": [
                    _make_result(
                        5,
                        data={
                            "pixiv_id": 99999,
                            "member_id": 1111,
                            "title": "My Art",
                            "member_name": "Artist",
                        },
                    )
                ]
            },
        )
        mock_pixiv = AsyncMock(return_value=({"Title": "Pixiv Art"}, {"provided_via": "Pixiv"}))

        with (
            patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp),
            patch("reverse_image_search_bot.engines.saucenao.pixiv.provide", mock_pixiv),
        ):
            _result, _meta = await engine.best_match("https://example.com/idx5.jpg")
            mock_pixiv.assert_awaited_once_with(99999)

    async def test_index_9_calls_danbooru(self, engine):
        """Index 9 = danbooru → _9_provider."""
        mock_resp = _mock_response(
            200,
            {"results": [_make_result(9, data={"danbooru_id": 555})]},
        )
        mock_booru = AsyncMock(return_value=({"Tags": "cat"}, {}))

        with (
            patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp),
            patch("reverse_image_search_bot.engines.saucenao.booru.provide", mock_booru),
        ):
            _result, _meta = await engine.best_match("https://example.com/idx9.jpg")
            mock_booru.assert_awaited_once_with("danbooru", 555)

    async def test_index_12_calls_yandere(self, engine):
        """Index 12 = yandere → _12_provider."""
        mock_resp = _mock_response(
            200,
            {"results": [_make_result(12, data={"yandere_id": 777})]},
        )
        mock_booru = AsyncMock(return_value=({"Tags": "landscape"}, {}))

        with (
            patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp),
            patch("reverse_image_search_bot.engines.saucenao.booru.provide", mock_booru),
        ):
            _result, _meta = await engine.best_match("https://example.com/idx12.jpg")
            mock_booru.assert_awaited_once_with("yandere", 777)

    async def test_index_25_calls_gelbooru(self, engine):
        """Index 25 = gelbooru → _25_provider."""
        mock_resp = _mock_response(
            200,
            {"results": [_make_result(25, data={"gelbooru_id": 888})]},
        )
        mock_booru = AsyncMock(return_value=({"Tags": "anime"}, {}))

        with (
            patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp),
            patch("reverse_image_search_bot.engines.saucenao.booru.provide", mock_booru),
        ):
            _result, _meta = await engine.best_match("https://example.com/idx25.jpg")
            mock_booru.assert_awaited_once_with("gelbooru", 888)

    async def test_index_37_calls_mangadex(self, engine):
        """Index 37 = mangadex → _37_provider."""
        mock_resp = _mock_response(
            200,
            {
                "results": [
                    _make_result(
                        37,
                        data={
                            "md_id": "abc-123",
                            "ext_urls": ["https://mangadex.org/chapter/abc-123"],
                        },
                    )
                ]
            },
        )
        mock_mangadex = AsyncMock(return_value=({"Title": "One Piece"}, {}))

        with (
            patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp),
            patch("reverse_image_search_bot.engines.saucenao.mangadex.provide", mock_mangadex),
        ):
            _result, _meta = await engine.best_match("https://example.com/idx37.jpg")
            mock_mangadex.assert_awaited_once()

    async def test_index_371_calls_mangadex(self, engine):
        """Index 371 = mangadex variant → _371_provider (delegates to _37_provider)."""
        mock_resp = _mock_response(
            200,
            {
                "results": [
                    _make_result(
                        371,
                        data={
                            "md_id": "def-456",
                            "ext_urls": ["https://mangadex.org/chapter/def-456"],
                        },
                    )
                ]
            },
        )
        mock_mangadex = AsyncMock(return_value=({"Title": "Naruto"}, {}))

        with (
            patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp),
            patch("reverse_image_search_bot.engines.saucenao.mangadex.provide", mock_mangadex),
        ):
            _result, _meta = await engine.best_match("https://example.com/idx371.jpg")
            mock_mangadex.assert_awaited_once()

    async def test_unknown_index_uses_default_provider(self, engine):
        """Unknown index falls back to _default_provider."""
        mock_resp = _mock_response(
            200,
            {
                "results": [
                    _make_result(
                        999,
                        data={
                            "creator": "someone",
                            "ext_urls": ["https://example.com/source"],
                        },
                    )
                ]
            },
        )

        with patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, meta = await engine.best_match("https://example.com/idx999.jpg")
            # _default_provider should extract creator and ext_urls
            assert result  # should have some data
            assert meta.get("provider") == "SauceNAO"

    async def test_priority_ordering_prefers_index_21(self, engine):
        """Index 21 (anilist) should be preferred over index 99 (unknown) even with lower similarity."""
        mock_resp = _mock_response(
            200,
            {
                "results": [
                    _make_result(99, similarity="90.0", data={"title": "Generic", "ext_urls": ["https://example.com"]}),
                    _make_result(21, similarity="85.0", data={"anilist_id": 12345, "part": 1}),
                ]
            },
        )
        mock_anilist = AsyncMock(return_value=({"Title": "Anime Result"}, {"provided_via": "Anilist"}))

        with (
            patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp),
            patch("reverse_image_search_bot.engines.saucenao.anilist.provide", mock_anilist),
        ):
            result, _meta = await engine.best_match("https://example.com/priority.jpg")
            assert result.get("Title") == "Anime Result"
