"""Tests for reverse_image_search_bot.engines.generic."""

from unittest.mock import MagicMock

import pytest
from telegram import InlineKeyboardButton
from yarl import URL

from reverse_image_search_bot.engines.generic import GenericRISEngine, PreWorkEngine


class TestGenericRISEngine:
    def test_init_defaults(self):
        engine = GenericRISEngine()
        assert engine.name == "GenericRISEngine"
        assert engine.types == []
        assert engine.url == ""

    def test_init_custom(self):
        engine = GenericRISEngine(
            name="TestEngine",
            url="https://example.com/?q={query_url}",
            description="A test engine",
            provider_url="https://example.com",
            types=["General"],
            recommendation=["Everything"],
        )
        assert engine.name == "TestEngine"
        assert engine.description == "A test engine"
        assert engine.provider_url == URL("https://example.com")
        assert engine.types == ["General"]
        assert engine.recommendation == ["Everything"]

    def test_get_search_link_by_url(self):
        engine = GenericRISEngine(url="https://example.com/?q={query_url}")
        link = engine.get_search_link_by_url("https://img.example.com/test.jpg")
        assert link == "https://example.com/?q=https%3A%2F%2Fimg.example.com%2Ftest.jpg"

    def test_call_returns_button(self):
        engine = GenericRISEngine(
            name="Test",
            url="https://example.com/?q={query_url}",
        )
        button = engine("https://img.example.com/test.jpg")
        assert isinstance(button, InlineKeyboardButton)
        assert button.text == "Test"

    def test_call_custom_text(self):
        engine = GenericRISEngine(
            name="Test",
            url="https://example.com/?q={query_url}",
        )
        button = engine("https://img.example.com/test.jpg", text="More")
        assert button.text == "More"


class TestCleanProviderData:
    def test_removes_none_values(self):
        engine = GenericRISEngine()
        result = engine._clean_privider_data({"Title": "Test", "Empty": None, "Blank": ""})
        assert "Title" in result
        assert "Empty" not in result
        assert "Blank" not in result

    def test_keeps_valid_values(self):
        engine = GenericRISEngine()
        result = engine._clean_privider_data({"Title": "Test", "Count": 0, "Flag": False})
        assert result["Title"] == "Test"
        assert result["Count"] == 0
        assert result["Flag"] is False


class TestCleanMetaData:
    def test_removes_invalid_button_urls(self):
        engine = GenericRISEngine()
        valid = MagicMock(spec=InlineKeyboardButton)
        valid.url = "https://example.com"
        invalid = MagicMock(spec=InlineKeyboardButton)
        invalid.url = "not-a-url"

        meta = {"buttons": [valid, invalid]}
        result = engine._clean_meta_data(meta)
        assert valid in result["buttons"]
        assert invalid not in result["buttons"]

    def test_empty_buttons(self):
        engine = GenericRISEngine()
        meta = {"buttons": []}
        result = engine._clean_meta_data(meta)
        assert result["buttons"] == []


class TestBestMatchImplemented:
    def test_base_class_not_implemented(self):
        assert not GenericRISEngine.best_match_implemented

    def test_subclass_with_override(self):
        class MyEngine(GenericRISEngine):
            async def best_match(self, url):
                return {}, {}

        assert MyEngine.best_match_implemented


@pytest.mark.asyncio
class TestGenericBestMatch:
    async def test_base_best_match_raises(self):
        engine = GenericRISEngine()
        engine._best_match_cache.clear()
        with pytest.raises(NotImplementedError):
            await engine.best_match("https://example.com/img.jpg")


class TestPreWorkEngine:
    def test_init(self):
        engine = PreWorkEngine(name="TestPre")
        assert engine.name == "TestPre"
        assert engine._http_client is not None

    def test_empty_button(self):
        engine = PreWorkEngine(name="TestPre")
        button = engine.empty_button()
        assert button.text == "⌛ TestPre"
        assert button.callback_data == "wait_for TestPre"

    @pytest.mark.asyncio
    async def test_resolve_raises_not_implemented(self):
        engine = PreWorkEngine(name="TestPre")
        with pytest.raises(NotImplementedError):
            await engine._resolve_search_url("https://example.com/img.jpg")

    @pytest.mark.asyncio
    async def test_call_returns_none_when_no_url(self):
        from unittest.mock import AsyncMock, patch

        engine = PreWorkEngine(name="TestPre")
        engine._url_cache.clear()
        with patch.object(engine, "_resolve_search_url", new_callable=AsyncMock, return_value=None):
            result = await engine("https://example.com/img.jpg")
            assert result is None

    @pytest.mark.asyncio
    async def test_call_returns_button_when_url(self):
        from unittest.mock import AsyncMock, patch

        engine = PreWorkEngine(name="TestPre")
        engine._url_cache.clear()
        with patch.object(
            engine, "_resolve_search_url", new_callable=AsyncMock, return_value="https://search.example.com/result"
        ):
            result = await engine("https://example.com/img2.jpg")
            assert result is not None
            assert result.text == "TestPre"
            assert result.url == "https://search.example.com/result"

    @pytest.mark.asyncio
    async def test_call_custom_text(self):
        from unittest.mock import AsyncMock, patch

        engine = PreWorkEngine(name="TestPre")
        engine._url_cache.clear()
        with patch.object(
            engine, "_resolve_search_url", new_callable=AsyncMock, return_value="https://search.example.com/result"
        ):
            result = await engine("https://example.com/img3.jpg", text="More")
            assert result.text == "More"
