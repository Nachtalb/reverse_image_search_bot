"""Tests for reverse_image_search_bot.engines.animetrace — pure logic helpers + extract."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from yarl import URL

from reverse_image_search_bot.engines.animetrace import (
    AnimeTraceEngine,
    _anilist_headers,
    _anilist_post,
    _anilist_resolve,
    _anilist_resolve_cache,
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
            {"title": {"native": "ナルト", "romaji": "Naruto", "english": "Naruto: The Series"}, "id": 2},
        ]
        title, mid = _best_work_node(nodes, "Naruto")
        assert title == "Naruto: The Series"
        assert mid == 2

    def test_fallback_to_most_popular(self):
        nodes = [
            {"title": {"native": "zzz", "romaji": "qqq", "english": "First"}, "id": 10},
            {"title": {"native": "xxx", "romaji": "www", "english": "Second"}, "id": 20},
        ]
        title, mid = _best_work_node(nodes, "YYYYYY")
        assert title == "First"
        assert mid == 10

    def test_english_fallback_to_romaji(self):
        nodes = [
            {"title": {"native": "テスト", "romaji": "Tesuto", "english": None}, "id": 5},
        ]
        title, mid = _best_work_node(nodes, "テスト")
        assert title == "Tesuto"
        assert mid == 5

    def test_fallback_no_english_no_romaji(self):
        """When both english and romaji are None in fallback, uses original_work."""
        nodes = [
            {"title": {"native": "zzz", "romaji": None, "english": None}, "id": 99},
        ]
        title, mid = _best_work_node(nodes, "YYYYYY")
        assert title == "YYYYYY"
        assert mid == 99


class TestAnilistHeaders:
    def test_with_token(self):
        with patch("reverse_image_search_bot.engines.animetrace.settings") as mock_s:
            mock_s.ANILIST_TOKEN = "test123"
            headers = _anilist_headers()
            assert headers["Authorization"] == "Bearer test123"

    def test_without_token(self):
        with patch("reverse_image_search_bot.engines.animetrace.settings") as mock_s:
            mock_s.ANILIST_TOKEN = None
            headers = _anilist_headers()
            assert headers == {}


@pytest.mark.asyncio
class TestAnilistPost:
    async def test_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"Character": {"name": {"full": "Test"}}}}
        mock_resp.headers = {}

        with patch("reverse_image_search_bot.engines.animetrace._anilist_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_resp)
            result = await _anilist_post({"query": "test", "variables": {}})
        assert result["data"]["Character"]["name"]["full"] == "Test"

    async def test_429_retries(self):
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {"Retry-After": "0"}

        mock_ok = MagicMock()
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"data": "ok"}
        mock_ok.headers = {}

        with patch("reverse_image_search_bot.engines.animetrace._anilist_client") as mock_client:
            mock_client.post = AsyncMock(side_effect=[mock_429, mock_ok])
            result = await _anilist_post({"query": "test", "variables": {}})
        assert result == {"data": "ok"}

    async def test_429_twice_returns_none(self):
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {"Retry-After": "0"}

        with patch("reverse_image_search_bot.engines.animetrace._anilist_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_429)
            result = await _anilist_post({"query": "test", "variables": {}})
        assert result is None


@pytest.mark.asyncio
class TestAnilistResolve:
    async def test_success(self):
        _anilist_resolve_cache.clear()
        anilist_data = {
            "data": {
                "Character": {
                    "id": 42,
                    "name": {"full": "Monkey D. Luffy"},
                    "siteUrl": "https://anilist.co/character/42",
                    "image": {"large": "https://img.anilist.co/char.jpg"},
                    "media": {
                        "nodes": [
                            {
                                "id": 21,
                                "type": "ANIME",
                                "siteUrl": "https://anilist.co/anime/21",
                                "title": {"english": "One Piece", "romaji": "One Piece", "native": "ワンピース"},
                            }
                        ]
                    },
                }
            }
        }

        with patch(
            "reverse_image_search_bot.engines.animetrace._anilist_post",
            new_callable=AsyncMock,
            return_value=anilist_data,
        ):
            en_name, en_work, char_id, media_id, char_image = await _anilist_resolve("ルフィ", "ワンピース")
        assert en_name == "Monkey D. Luffy"
        assert en_work == "One Piece"
        assert char_id == 42
        assert media_id == 21
        assert char_image == "https://img.anilist.co/char.jpg"

    async def test_cache_hit(self):
        _anilist_resolve_cache.clear()
        _anilist_resolve_cache[("cached", "work")] = ("CachedName", "CachedWork", 1, 2, "img.jpg")
        result = await _anilist_resolve("cached", "work")
        assert result == ("CachedName", "CachedWork", 1, 2, "img.jpg")

    async def test_failure_falls_back(self):
        _anilist_resolve_cache.clear()
        with patch(
            "reverse_image_search_bot.engines.animetrace._anilist_post",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ):
            en_name, en_work, char_id, media_id, char_image = await _anilist_resolve("OrigChar", "OrigWork")
        assert en_name == "OrigChar"
        assert en_work == "OrigWork"
        assert char_id is None
        assert media_id is None
        assert char_image is None


@pytest.mark.asyncio
class TestAnimeTraceSearch:
    async def test_keyerror_returns_empty_raw(self):
        engine = AnimeTraceEngine()
        engine._best_match_cache.clear()

        with patch("PicImageSearch.Network") as mock_network:
            mock_ctx = AsyncMock()
            mock_network.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_network.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("PicImageSearch.AnimeTrace") as mock_at_cls:
                mock_at_instance = AsyncMock()
                mock_at_instance.search = AsyncMock(side_effect=KeyError("trace_id"))
                mock_at_cls.return_value = mock_at_instance

                result, meta = await engine.best_match("https://example.com/no-result.jpg")
                assert result == {}
                assert meta == {}


def _mock_character(name, work):
    return type("Character", (), {"name": name, "work": work})()


def _mock_item(characters, not_confident=False, thumbnail=None):
    return type(
        "Item",
        (),
        {"origin": {"not_confident": not_confident}, "characters": characters, "thumbnail": thumbnail},
    )()


@pytest.mark.asyncio
class TestAnimeTraceExtract:
    async def test_empty_confident_returns_empty(self):
        engine = AnimeTraceEngine()
        mock_item = _mock_item([], not_confident=True)
        result, meta = await engine._extract([mock_item])
        assert result == {}
        assert meta == {}

    async def test_no_characters_returns_empty(self):
        engine = AnimeTraceEngine()
        mock_item = _mock_item(characters=[], not_confident=False)
        result, meta = await engine._extract([mock_item])
        assert result == {}
        assert meta == {}

    async def test_single_confident_item(self):
        _anilist_resolve_cache.clear()
        engine = AnimeTraceEngine()

        mock_item = _mock_item(
            characters=[_mock_character("ルフィ", "ワンピース")],
            not_confident=False,
            thumbnail="https://example.com/thumb.jpg",
        )

        resolve_result = ("Monkey D. Luffy", "One Piece", 42, 21, "https://img.anilist.co/char.jpg")
        anilist_result = (
            {"Title": "One Piece", "Title [romaji]": "One Piece", "Episode": "?/1000", "Status": "ONGOING"},
            {"provided_via": "Anilist", "provided_via_url": URL("https://anilist.co/"), "buttons": []},
        )

        with (
            patch(
                "reverse_image_search_bot.engines.animetrace._anilist_resolve",
                new_callable=AsyncMock,
                return_value=resolve_result,
            ),
            patch(
                "reverse_image_search_bot.engines.animetrace.anilist_provider.provide",
                new_callable=AsyncMock,
                return_value=anilist_result,
            ),
        ):
            result, meta = await engine._extract([mock_item])

        assert result["Character"] == "Monkey D. Luffy"
        assert result["Work"] == "One Piece"
        assert result["Status"] == "ONGOING"
        assert "Title" not in result  # Stripped by _extract
        assert meta["thumbnail"] == URL("https://example.com/thumb.jpg")

    async def test_single_item_no_thumbnail_uses_char_image(self):
        _anilist_resolve_cache.clear()
        engine = AnimeTraceEngine()

        mock_item = _mock_item(
            characters=[_mock_character("Test", "Work")],
            not_confident=False,
            thumbnail=None,
        )

        resolve_result = ("Test EN", "Work EN", 10, 20, "https://img.anilist.co/char_portrait.jpg")

        with (
            patch(
                "reverse_image_search_bot.engines.animetrace._anilist_resolve",
                new_callable=AsyncMock,
                return_value=resolve_result,
            ),
            patch(
                "reverse_image_search_bot.engines.animetrace.anilist_provider.provide",
                new_callable=AsyncMock,
                return_value=({}, {}),
            ),
        ):
            _result, meta = await engine._extract([mock_item])

        assert meta["thumbnail"] == URL("https://img.anilist.co/char_portrait.jpg")

    async def test_single_item_no_char_image_uses_anilist_thumb(self):
        _anilist_resolve_cache.clear()
        engine = AnimeTraceEngine()

        mock_item = _mock_item(
            characters=[_mock_character("Test", "Work")],
            not_confident=False,
            thumbnail=None,
        )

        resolve_result = ("Test EN", "Work EN", 10, 20, None)
        al_thumb = URL("https://img.anilist.co/cover.jpg")

        with (
            patch(
                "reverse_image_search_bot.engines.animetrace._anilist_resolve",
                new_callable=AsyncMock,
                return_value=resolve_result,
            ),
            patch(
                "reverse_image_search_bot.engines.animetrace.anilist_provider.provide",
                new_callable=AsyncMock,
                return_value=({}, {"thumbnail": al_thumb}),
            ),
        ):
            _result, meta = await engine._extract([mock_item])

        assert meta["thumbnail"] == al_thumb

    async def test_single_item_with_alternatives(self):
        _anilist_resolve_cache.clear()
        engine = AnimeTraceEngine()

        chars = [
            _mock_character("Main", "MainWork"),
            _mock_character("Alt1", "AltWork1"),
            _mock_character("Alt2", "AltWork2"),
        ]
        mock_item = _mock_item(characters=chars, thumbnail="https://example.com/t.jpg")

        async def fake_resolve(name, work):
            return f"{name} EN", f"{work} EN", None, None, None

        with (
            patch(
                "reverse_image_search_bot.engines.animetrace._anilist_resolve",
                side_effect=fake_resolve,
            ),
            patch(
                "reverse_image_search_bot.engines.animetrace.anilist_provider.provide",
                new_callable=AsyncMock,
                return_value=({}, {}),
            ),
        ):
            result, _meta = await engine._extract([mock_item])

        assert "Also possible" in result
        assert "Alt1 EN" in result["Also possible"]
        assert "Alt2 EN" in result["Also possible"]

    async def test_single_item_with_buttons_from_anilist(self):
        """Test that buttons from anilist are combined with character button."""
        _anilist_resolve_cache.clear()
        engine = AnimeTraceEngine()

        from telegram import InlineKeyboardButton

        mock_item = _mock_item(
            characters=[_mock_character("WithButtons", "ButtonWork")],
            thumbnail="https://example.com/t.jpg",
        )

        al_button = InlineKeyboardButton("🌐 Anilist", url="https://anilist.co/anime/21")
        resolve_result = ("WithButtons EN", "ButtonWork EN", 42, 21, None)

        with (
            patch(
                "reverse_image_search_bot.engines.animetrace._anilist_resolve",
                new_callable=AsyncMock,
                return_value=resolve_result,
            ),
            patch(
                "reverse_image_search_bot.engines.animetrace.anilist_provider.provide",
                new_callable=AsyncMock,
                return_value=({}, {"buttons": [al_button]}),
            ),
        ):
            _result, meta = await engine._extract([mock_item])

        assert "buttons" in meta
        # Should have char button + anilist button
        assert len(meta["buttons"]) == 2
        assert any("character/42" in b.url for b in meta["buttons"])
        assert any("anilist.co" in b.url for b in meta["buttons"])

    async def test_single_item_no_media_id(self):
        _anilist_resolve_cache.clear()
        engine = AnimeTraceEngine()

        mock_item = _mock_item(
            characters=[_mock_character("Solo", "SoloWork")],
            thumbnail="https://example.com/t.jpg",
        )

        resolve_result = ("Solo EN", "SoloWork EN", 5, None, None)

        with patch(
            "reverse_image_search_bot.engines.animetrace._anilist_resolve",
            new_callable=AsyncMock,
            return_value=resolve_result,
        ):
            result, meta = await engine._extract([mock_item])

        assert result["Character"] == "Solo EN"
        assert "buttons" in meta
        assert any("character/5" in b.url for b in meta["buttons"])

    async def test_multiple_confident_items(self):
        _anilist_resolve_cache.clear()
        engine = AnimeTraceEngine()

        items = [
            _mock_item(characters=[_mock_character("Char1", "Work1")], thumbnail="https://example.com/t.jpg"),
            _mock_item(characters=[_mock_character("Char2", "Work2")]),
        ]

        async def fake_resolve(name, work):
            return f"{name} EN", f"{work} EN", None, None, None

        with patch(
            "reverse_image_search_bot.engines.animetrace._anilist_resolve",
            side_effect=fake_resolve,
        ):
            result, _meta = await engine._extract(items)

        assert "Characters" in result
        assert "Char1 EN" in result["Characters"]
        assert "Char2 EN" in result["Characters"]

    async def test_multiple_items_no_characters(self):
        _anilist_resolve_cache.clear()
        engine = AnimeTraceEngine()

        items = [
            _mock_item(characters=[]),
            _mock_item(characters=[]),
        ]

        result, _meta = await engine._extract(items)
        assert result == {}

    async def test_single_item_duplicate_alt_skipped(self):
        """Alternative characters with the same name as the top character should be skipped."""
        _anilist_resolve_cache.clear()
        engine = AnimeTraceEngine()

        chars = [
            _mock_character("Same", "Work"),
            _mock_character("Same", "Work"),  # Same name → skipped
        ]
        mock_item = _mock_item(characters=chars, thumbnail="https://example.com/t.jpg")

        async def fake_resolve(name, work):
            return "Same EN", "Work EN", None, None, None

        with (
            patch("reverse_image_search_bot.engines.animetrace._anilist_resolve", side_effect=fake_resolve),
            patch(
                "reverse_image_search_bot.engines.animetrace.anilist_provider.provide",
                new_callable=AsyncMock,
                return_value=({}, {}),
            ),
        ):
            result, _meta = await engine._extract([mock_item])

        assert "Also possible" not in result
