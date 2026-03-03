"""Tests for reverse_image_search_bot.engines.pic_image_search."""

from unittest.mock import AsyncMock, MagicMock, patch

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
            mock.side_effect = KeyError("some_field")
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


class TestClassProperties:
    def test_best_match_implemented_is_true(self):
        assert ConcretePIS.best_match_implemented is True


@pytest.mark.asyncio
class TestBaseSearch:
    async def test_search_calls_pic_engine(self):
        """Test the base _search method with a mocked Network and engine class."""

        class FakeEngine:
            def __init__(self, client):
                self.client = client

            async def search(self, url):
                return type("Result", (), {"raw": [{"title": "found"}]})()

        class TestableEngine(PicImageSearchEngine):
            name = "TestSearchable"
            provider_url = URL("https://test.example.com")
            pic_engine_class = FakeEngine

        engine = TestableEngine()
        mock_network = AsyncMock()
        mock_network.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_network.__aexit__ = AsyncMock(return_value=False)

        # Network is imported locally inside _search, so patch the import source
        with patch("PicImageSearch.Network", return_value=mock_network, create=True):
            result = await engine._search("https://example.com/test.jpg")
            assert hasattr(result, "raw")

    async def test_search_asserts_no_pic_engine_class(self):
        """_search should assert if pic_engine_class is None."""

        class NoEngineClass(PicImageSearchEngine):
            name = "NoEngine"
            provider_url = URL("https://test.example.com")
            pic_engine_class = None

        engine = NoEngineClass()
        mock_network = AsyncMock()
        mock_network.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_network.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("PicImageSearch.Network", return_value=mock_network, create=True),
            pytest.raises(AssertionError, match="pic_engine_class must be set"),
        ):
            await engine._search("https://example.com/test.jpg")


@pytest.mark.asyncio
class TestParsingError:
    async def test_parsing_error_raises_search_error(self):
        engine = ConcretePIS()
        engine._best_match_cache.clear()

        # Create a fake ParsingError class since we can't reliably import it
        from PicImageSearch.exceptions import ParsingError

        # ParsingError requires (msg, engine) args
        err = ParsingError.__new__(ParsingError)
        Exception.__init__(err, "bad html")

        with (
            patch.object(engine, "_search", new_callable=AsyncMock, side_effect=err),
            pytest.raises(SearchError, match="ParsingError"),
        ):
            await engine.best_match("https://example.com/parse_err.jpg")

    async def test_generic_exception_raises_search_error(self):
        engine = ConcretePIS()
        engine._best_match_cache.clear()

        with (
            patch.object(engine, "_search", new_callable=AsyncMock, side_effect=RuntimeError("unexpected")),
            pytest.raises(SearchError, match="Search failed"),
        ):
            await engine.best_match("https://example.com/generic_err.jpg")


@pytest.mark.asyncio
class TestExtractionYieldsNothing:
    async def test_extract_returns_empty(self):
        engine = ConcretePIS()
        engine._best_match_cache.clear()

        raw_item = type("RawItem", (), {"title": None, "url": None, "thumbnail": None})()

        with patch.object(engine, "_search", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = type("Result", (), {"raw": [raw_item]})()

            with patch.object(engine, "_extract", new_callable=AsyncMock, return_value=({}, {})):
                result, meta = await engine.best_match("https://example.com/empty_extract.jpg")
                assert result == {}
                assert meta == {}
