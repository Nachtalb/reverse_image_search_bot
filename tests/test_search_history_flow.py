"""The search flow's history side-effects: when an entry is opened, and what lands in it."""

from __future__ import annotations

from unittest.mock import MagicMock

from telegram import InlineKeyboardButton
from yarl import URL

from reverse_image_search_bot.commands.search import _history_entry
from reverse_image_search_bot.engines.types import MetaData


class TestHistoryEntry:
    """One engine's answer, flattened to the small JSON the history app renders."""

    def test_takes_the_first_textual_field_as_the_title(self):
        entry = _history_entry("SauceNAO", {"Title": "A Painting", "Pages": 12}, {})
        assert entry["engine"] == "SauceNAO"
        assert entry["title"] == "A Painting"

    def test_skips_blank_and_non_string_fields_when_titling(self):
        entry = _history_entry("SauceNAO", {"Pages": 12, "Empty": "   ", "Title": "Real"}, {})
        assert entry["title"] == "Real"

    def test_no_title_when_nothing_textual(self):
        assert "title" not in _history_entry("SauceNAO", {"Pages": 12}, {})

    def test_long_titles_are_truncated(self):
        entry = _history_entry("SauceNAO", {"Title": "x" * 500}, {})
        assert len(entry["title"]) == 200

    def test_takes_the_first_button_url_as_the_link(self):
        meta: MetaData = {
            "buttons": [
                InlineKeyboardButton(text="cb", callback_data="nope"),
                InlineKeyboardButton(text="Source", url="https://example.com/post/1"),
                InlineKeyboardButton(text="Other", url="https://example.com/post/2"),
            ]
        }
        assert _history_entry("SauceNAO", {}, meta)["url"] == "https://example.com/post/1"

    def test_no_link_when_no_button_has_one(self):
        meta: MetaData = {"buttons": [InlineKeyboardButton(text="cb", callback_data="nope")]}
        assert "url" not in _history_entry("SauceNAO", {}, meta)

    def test_thumbnail_url_is_stringified(self):
        entry = _history_entry("SauceNAO", {}, {"thumbnail": URL("https://example.com/t.jpg")})
        assert entry["thumbnail"] == "https://example.com/t.jpg"
        assert isinstance(entry["thumbnail"], str)

    def test_first_thumbnail_when_several(self):
        meta: MetaData = {"thumbnail": [URL("https://a/1.jpg"), URL("https://b/2.jpg")]}
        assert _history_entry("SauceNAO", {}, meta)["thumbnail"] == "https://a/1.jpg"

    def test_empty_thumbnail_list_is_omitted(self):
        assert "thumbnail" not in _history_entry("SauceNAO", {}, {"thumbnail": []})

    def test_similarity_is_rounded(self):
        assert _history_entry("SauceNAO", {}, {"similarity": 92.4567})["similarity"] == 92.5

    def test_zero_similarity_is_kept(self):
        """0.0 is a real score, not a missing one."""
        assert _history_entry("SauceNAO", {}, {"similarity": 0})["similarity"] == 0.0

    def test_result_is_plain_json(self):
        """yarl.URL / sets in the payload must not leak into the stored row."""
        import json

        result = {"Title": "T", "Source": URL("https://e.com"), "Tags": {"a", "b"}}
        meta: MetaData = {
            "thumbnail": URL("https://e.com/t.jpg"),
            "similarity": 90,
            "buttons": [InlineKeyboardButton(text="B", url="https://e.com/1")],
        }
        entry = _history_entry("SauceNAO", result, meta)
        assert json.loads(json.dumps(entry)) == entry

    def test_a_bare_engine_answer_still_yields_an_entry(self):
        assert _history_entry("Yandex", {}, {}) == {"engine": "Yandex"}


class TestRecordingIsPrivateChatsOnly:
    """History is personal: group traffic must not land in a user's private list."""

    def _abuse(self, monkeypatch, tmp_path):
        import importlib

        import reverse_image_search_bot.settings as settings

        monkeypatch.setattr(settings, "ABUSE_DB_PATH", tmp_path / "abuse.db")
        import reverse_image_search_bot.config.abuse as ab

        ab._local.__dict__.clear()
        ab._all_connections.clear()
        importlib.reload(ab)
        monkeypatch.setattr(ab, "ABUSE_DB_PATH", tmp_path / "abuse.db")
        ab._local.__dict__.clear()
        ab._all_connections.clear()
        return ab

    def test_private_search_is_recorded(self, monkeypatch, tmp_path):
        ab = self._abuse(monkeypatch, tmp_path)
        ab.record_user(5)
        ab.record_search(5, chat_id=5, message_id=1, file_unique_id="F1")
        assert ab.count_user_searches(5) == 1

    def test_the_guard_matches_the_flow(self):
        """The condition in file_handler is `chat_type == private and not held`."""
        import inspect

        from reverse_image_search_bot.commands import search as mod

        src = inspect.getsource(mod.file_handler)
        assert 'chat_type == "private"' in src
        assert "hold_reason is None" in src
        assert "record_search" in src

    def test_results_are_written_after_the_engines_finish(self):
        import inspect

        from reverse_image_search_bot.commands import search as mod

        src = inspect.getsource(mod._best_match_search)
        assert "set_search_results" in src
        # Guarded, so a history failure cannot break the search itself.
        assert "contextlib.suppress" in src


class TestHistoryFailuresAreHarmless:
    def test_entry_builder_tolerates_a_meta_without_buttons(self):
        assert _history_entry("E", {"Title": "x"}, {"provider": "E"})["title"] == "x"

    def test_entry_builder_tolerates_odd_button_objects(self):
        odd = MagicMock(spec=[])  # no .url attribute at all
        assert "url" not in _history_entry("E", {}, {"buttons": [odd]})
