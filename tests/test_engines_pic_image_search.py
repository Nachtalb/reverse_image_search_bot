"""Tests for reverse_image_search_bot.engines.pic_image_search."""

from unittest.mock import AsyncMock, patch

import pytest
from yarl import URL

from reverse_image_search_bot.engines.errors import SearchError
from reverse_image_search_bot.engines.pic_image_search import PicImageSearchEngine


class ConcretePIS(PicImageSearchEngine):
    """Concrete subclass for testing."""

    name = "TestPIS"
    provider_url = URL("https://test.example.com")

    async def _search(self, url: str):
        raise NotImplementedError("Override in test")


@pytest.mark.asyncio
class TestBestMatch:
    async def test_no_results(self):
        engine = ConcretePIS()
        engine._best_match_cache.clear()

        with patch.object(engine, "_search", new_callable=AsyncMock) as mock:
            mock.return_value = type("Result", (), {"raw": []})()
            result, meta = await engine.best_match("https://example.com/img.jpg")
            assert result == {}
            assert meta == {}

    async def test_no_raw_attr(self):
        engine = ConcretePIS()
        engine._best_match_cache.clear()

        with patch.object(engine, "_search", new_callable=AsyncMock) as mock:
            mock.return_value = type("Result", (), {"raw": None})()
            result, _meta = await engine.best_match("https://example.com/img2.jpg")
            assert result == {}

    async def test_keyerror_raises_search_error(self):
        engine = ConcretePIS()
        engine._best_match_cache.clear()

        with patch.object(engine, "_search", new_callable=AsyncMock) as mock:
            mock.side_effect = KeyError("trace_id")
            with pytest.raises(SearchError, match="Parsing key missing"):
                await engine.best_match("https://example.com/img3.jpg")

    async def test_extraction_failure_raises_search_error(self):
        engine = ConcretePIS()
        engine._best_match_cache.clear()

        with patch.object(engine, "_search", new_callable=AsyncMock) as mock_search:
            raw_item = type("RawItem", (), {"title": "Test", "url": "https://ex.com", "thumbnail": None})()
            mock_search.return_value = type("Result", (), {"raw": [raw_item]})()

            with patch.object(engine, "_extract", new_callable=AsyncMock) as mock_extract:
                mock_extract.side_effect = ValueError("bad data")
                with pytest.raises(SearchError, match="Extraction failed"):
                    await engine.best_match("https://example.com/img4.jpg")

    async def test_successful_extraction(self):
        engine = ConcretePIS()
        engine._best_match_cache.clear()

        with patch.object(engine, "_search", new_callable=AsyncMock) as mock_search:
            raw_item = type(
                "RawItem", (), {"title": "Test", "url": "https://ex.com", "thumbnail": "https://ex.com/t.jpg"}
            )()
            mock_search.return_value = type("Result", (), {"raw": [raw_item]})()

            result, meta = await engine.best_match("https://example.com/img5.jpg")
            assert result.get("Title") == "Test"
            assert meta.get("provider") == "TestPIS"


@pytest.mark.asyncio
class TestDefaultExtract:
    async def test_extracts_title_and_thumbnail(self):
        engine = ConcretePIS()
        raw_item = type(
            "RawItem",
            (),
            {"title": "Hello", "url": "https://example.com", "thumbnail": "https://example.com/thumb.jpg"},
        )()
        result, meta = await engine._extract([raw_item])
        assert result["Title"] == "Hello"
        assert meta["thumbnail"] == URL("https://example.com/thumb.jpg")

    async def test_missing_attrs(self):
        engine = ConcretePIS()
        raw_item = type("RawItem", (), {})()
        result, _meta = await engine._extract([raw_item])
        assert result == {}
