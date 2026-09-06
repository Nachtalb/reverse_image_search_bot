"""Paging through several candidate results of one engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import InlineKeyboardButton, Update
from yarl import URL

from reverse_image_search_bot.commands import result_pager
from reverse_image_search_bot.commands.search import build_result_buttons, show_result_page
from reverse_image_search_bot.engines.generic import GenericRISEngine
from reverse_image_search_bot.engines.types import ProviderData, ProviderMatches


@pytest.fixture(autouse=True)
def _clean_store():
    result_pager._STORE.clear()
    yield
    result_pager._STORE.clear()


MATCH_A: ProviderData = ({"Title": "First"}, {"provider": "SauceNAO", "provider_url": URL("https://saucenao.com")})
MATCH_B: ProviderData = ({"Title": "Second"}, {"provider": "SauceNAO", "provider_url": URL("https://saucenao.com")})
MATCH_C: ProviderData = ({"Title": "Third"}, {"provider": "SauceNAO", "provider_url": URL("https://saucenao.com")})
EMPTY: ProviderData = ({}, {})


class TestStore:
    def test_round_trip(self):
        token = result_pager.store_matches("SauceNAO", "https://x/1.jpg", [MATCH_A, MATCH_B])
        stored = result_pager.get_matches(token)
        assert stored is not None
        assert stored.engine_name == "SauceNAO"
        assert stored.url == "https://x/1.jpg"
        assert len(stored.matches) == 2

    def test_unknown_token_is_none(self):
        assert result_pager.get_matches("nope") is None

    def test_tokens_are_unique(self):
        a = result_pager.store_matches("E", "u", [MATCH_A])
        b = result_pager.store_matches("E", "u", [MATCH_A])
        assert a != b

    def test_token_fits_telegram_callback_data(self):
        """callback_data is capped at 64 BYTES — 'page <token> <index>' must fit."""
        token = result_pager.store_matches("SauceNAO", "https://x/1.jpg", [MATCH_A])
        assert len(f"page {token} 99".encode()) <= 64


class TestAllMatches:
    async def test_drops_empty_candidates(self):
        class Engine(GenericRISEngine):
            name = "E"

            async def _all_matches(self, url) -> ProviderMatches:
                return [MATCH_A, EMPTY, MATCH_B]

        assert len(await Engine().all_matches(URL("https://x/1.jpg"))) == 2

    async def test_caps_at_max_results(self):
        class Engine(GenericRISEngine):
            name = "E2"
            max_results = 2

            async def _all_matches(self, url) -> ProviderMatches:
                return [MATCH_A, MATCH_B, MATCH_C]

        assert len(await Engine().all_matches(URL("https://x/2.jpg"))) == 2

    async def test_best_match_is_the_first_candidate(self):
        class Engine(GenericRISEngine):
            name = "E3"

            async def _all_matches(self, url) -> ProviderMatches:
                return [MATCH_A, MATCH_B]

        result, _meta = await Engine().best_match(URL("https://x/3.jpg"))
        assert result["Title"] == "First"

    async def test_best_match_of_nothing_is_empty(self):
        class Engine(GenericRISEngine):
            name = "E4"

            async def _all_matches(self, url) -> ProviderMatches:
                return []

        assert await Engine().best_match(URL("https://x/4.jpg")) == ({}, {})

    def test_an_engine_overriding_only_all_matches_counts_as_implemented(self):
        class Engine(GenericRISEngine):
            async def _all_matches(self, url) -> ProviderMatches:
                return []

        assert Engine.best_match_implemented

    def test_the_base_engine_is_not_implemented(self):
        assert not GenericRISEngine.best_match_implemented


class TestButtons:
    def _engine(self):
        engine = MagicMock(spec=GenericRISEngine)
        engine.name = "SauceNAO"
        engine.return_value = InlineKeyboardButton(text="More", url="https://more")
        return engine

    def test_no_nav_row_for_a_single_result(self):
        rows = build_result_buttons(self._engine(), "https://x/1.jpg", {}, "en", token=None, index=0, total=1)
        assert all("page " not in str(b.callback_data or "") for row in rows for b in row)

    def test_nav_row_when_there_are_several(self):
        rows = build_result_buttons(self._engine(), "https://x/1.jpg", {}, "en", token="tok", index=0, total=3)
        nav = [b for row in rows for b in row if str(b.callback_data or "").startswith("page ")]
        assert len(nav) == 2

    def test_paging_wraps_around(self):
        """Previous from the first result goes to the last, and back again."""
        rows = build_result_buttons(self._engine(), "https://x/1.jpg", {}, "en", token="tok", index=0, total=3)
        nav = [b.callback_data for row in rows for b in row if str(b.callback_data or "").startswith("page ")]
        assert nav == ["page tok 2", "page tok 1"]

        rows = build_result_buttons(self._engine(), "https://x/1.jpg", {}, "en", token="tok", index=2, total=3)
        nav = [b.callback_data for row in rows for b in row if str(b.callback_data or "").startswith("page ")]
        assert nav == ["page tok 1", "page tok 0"]


class TestShowResultPage:
    def _update(self):
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_chat = MagicMock(id=1, type="private")
        update.effective_user = MagicMock(id=1, language_code="en")
        return update

    async def test_expired_token_tells_the_user(self):
        update = self._update()
        await show_result_page(update, MagicMock(), "gone", "1")
        assert update.callback_query.answer.call_args.kwargs.get("show_alert") is True
        update.callback_query.edit_message_text.assert_not_called()

    async def test_unknown_engine_does_not_crash(self):
        token = result_pager.store_matches("NoSuchEngine", "https://x/1.jpg", [MATCH_A, MATCH_B])
        update = self._update()
        await show_result_page(update, MagicMock(), token, "1")
        update.callback_query.edit_message_text.assert_not_called()

    async def test_a_non_numeric_index_does_not_crash(self):
        token = result_pager.store_matches("SauceNAO", "https://x/1.jpg", [MATCH_A, MATCH_B])
        update = self._update()
        await show_result_page(update, MagicMock(), token, "abc")
        update.callback_query.edit_message_text.assert_not_called()

    async def test_edits_the_message_to_the_requested_result(self):
        token = result_pager.store_matches("SauceNAO", "https://x/1.jpg", [MATCH_A, MATCH_B])
        update = self._update()
        await show_result_page(update, MagicMock(), token, "1")
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Second" in text

    async def test_an_out_of_range_index_wraps(self):
        token = result_pager.store_matches("SauceNAO", "https://x/1.jpg", [MATCH_A, MATCH_B])
        update = self._update()
        await show_result_page(update, MagicMock(), token, "7")
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Second" in text  # 7 % 2 == 1

    async def test_a_callback_without_a_query_is_ignored(self):
        update = MagicMock(spec=Update)
        update.callback_query = None
        await show_result_page(update, MagicMock(), "tok", "0")  # must not raise
