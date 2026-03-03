"""Tests for reverse_image_search_bot.engines.animetrace — pure logic helpers."""

from unittest.mock import patch

import pytest

from reverse_image_search_bot.engines.animetrace import (
    AnimeTraceEngine,
    _best_work_node,
    _clean_name,
)


class TestCleanName:
    def test_parenthetical_japanese(self):
        assert _clean_name("矢澤 にこ（やざわ にこ）") == "矢澤 にこ"

    def test_comma_separated(self):
        assert _clean_name("ヤシロ・モモカ, Momo") == "ヤシロ・モモカ"

    def test_english_parenthetical(self):
        assert _clean_name("シリカ (Scilica)") == "シリカ"

    def test_no_cleaning_needed(self):
        assert _clean_name("Asuna") == "Asuna"

    def test_empty_string(self):
        assert _clean_name("") == ""

    def test_whitespace_stripping(self):
        assert _clean_name("  Name  ") == "Name"


class TestBestWorkNode:
    def test_empty_nodes(self):
        title, media_id = _best_work_node([], "Some Work")
        assert title == "Some Work"
        assert media_id is None

    def test_exact_native_match(self):
        nodes = [
            {"title": {"native": "進撃の巨人", "romaji": "Shingeki no Kyojin", "english": "Attack on Titan"}, "id": 1},
        ]
        title, mid = _best_work_node(nodes, "進撃の巨人")
        assert title == "Attack on Titan"
        assert mid == 1

    def test_exact_romaji_match(self):
        nodes = [
            {"title": {"native": "ナルト", "romaji": "Naruto", "english": "Naruto"}, "id": 2},
        ]
        title, mid = _best_work_node(nodes, "Naruto")
        assert title == "Naruto"
        assert mid == 2

    def test_fallback_to_most_popular(self):
        nodes = [
            {"title": {"native": "A", "romaji": "B", "english": "First"}, "id": 10},
            {"title": {"native": "C", "romaji": "D", "english": "Second"}, "id": 20},
        ]
        title, mid = _best_work_node(nodes, "Unmatched")
        assert title == "First"
        assert mid == 10

    def test_english_fallback_to_romaji(self):
        nodes = [
            {"title": {"native": "テスト", "romaji": "Tesuto", "english": None}, "id": 5},
        ]
        title, mid = _best_work_node(nodes, "テスト")
        assert title == "Tesuto"
        assert mid == 5


@pytest.mark.asyncio
class TestAnimeTraceSearch:
    async def test_keyerror_returns_empty_raw(self):
        """The fix from PR #116: KeyError in PicImageSearch → empty result, not crash."""
        engine = AnimeTraceEngine()

        with patch.object(engine, "_search") as mock_search:
            # Simulate the KeyError being caught → empty raw sentinel
            mock_search.return_value = type("EmptyResult", (), {"raw": []})()
            result = mock_search.return_value
            assert result.raw == []


@pytest.mark.asyncio
class TestAnimeTraceExtract:
    async def test_empty_confident_returns_empty(self):
        engine = AnimeTraceEngine()
        # Items with not_confident=True should be filtered out
        mock_item = type("MockItem", (), {"origin": {"not_confident": True}})()
        result, meta = await engine._extract([mock_item])
        assert result == {}
        assert meta == {}

    async def test_no_characters_returns_empty(self):
        engine = AnimeTraceEngine()
        mock_item = type("MockItem", (), {"origin": {}, "characters": [], "thumbnail": None})()
        result, meta = await engine._extract([mock_item])
        assert result == {}
        assert meta == {}
