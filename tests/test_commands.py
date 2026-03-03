"""Tests for pure functions in reverse_image_search_bot.commands."""

from unittest.mock import MagicMock, patch

import pytest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from yarl import URL

from reverse_image_search_bot.commands import (
    _button_count,
    _extract_video_frame,
    _is_group,
    _settings_engines_keyboard,
    _settings_main_keyboard,
    _settings_main_text,
    _track_engine_result,
    build_reply,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_chat_config(**overrides):
    """Build a mock ChatConfig with sensible defaults."""
    defaults = {
        "auto_search_enabled": True,
        "show_buttons": True,
        "show_best_match": True,
        "show_link": True,
        "auto_search_engines": None,  # None = all enabled
        "button_engines": None,
        "engine_empty_counts": {},
    }
    defaults.update(overrides)
    cfg = MagicMock()
    for k, v in defaults.items():
        setattr(cfg, k, v)
    return cfg


def _flat_buttons(keyboard: InlineKeyboardMarkup) -> list[InlineKeyboardButton]:
    """Flatten all buttons from a keyboard."""
    return [btn for row in keyboard.inline_keyboard for btn in row]


def _button_texts(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [btn.text for btn in _flat_buttons(keyboard)]


def _button_callbacks(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [btn.callback_data for btn in _flat_buttons(keyboard)]


# ---------------------------------------------------------------------------
# _is_group
# ---------------------------------------------------------------------------


class TestIsGroup:
    def test_negative_is_group(self):
        assert _is_group(-100123456) is True

    def test_positive_is_not_group(self):
        assert _is_group(123456) is False

    def test_zero_is_not_group(self):
        assert _is_group(0) is False


# ---------------------------------------------------------------------------
# _settings_main_text
# ---------------------------------------------------------------------------


class TestSettingsMainText:
    def test_returns_html(self):
        cfg = _mock_chat_config()
        text = _settings_main_text(cfg)
        assert text == "⚙️ <b>Chat Settings</b>\nConfigure how the bot behaves in this chat."


# ---------------------------------------------------------------------------
# _settings_main_keyboard
# ---------------------------------------------------------------------------


class TestSettingsMainKeyboard:
    def test_all_enabled(self):
        cfg = _mock_chat_config(auto_search_enabled=True, show_buttons=True)
        kb = _settings_main_keyboard(cfg)
        texts = _button_texts(kb)
        callbacks = _button_callbacks(kb)

        assert "🔍 Auto-search: ✅" in texts
        assert "🔘 Show buttons: ✅" in texts
        assert "🔍 Auto-search engines →" in texts
        assert "🔘 Engine buttons →" in texts

        assert "settings:toggle:auto_search" in callbacks
        assert "settings:toggle:show_buttons" in callbacks
        assert "settings:menu:auto_search_engines" in callbacks
        assert "settings:menu:button_engines" in callbacks

    def test_all_disabled(self):
        cfg = _mock_chat_config(auto_search_enabled=False, show_buttons=False)
        kb = _settings_main_keyboard(cfg)
        texts = _button_texts(kb)
        callbacks = _button_callbacks(kb)

        assert "🔍 Auto-search: ❌" in texts
        assert "🔘 Show buttons: ❌" in texts
        assert "🔍 Auto-search engines 🔒" in texts
        assert "🔘 Engine buttons 🔒" in texts

        assert "settings:disabled:auto_search_engines" in callbacks
        assert "settings:disabled:button_engines" in callbacks


# ---------------------------------------------------------------------------
# _settings_engines_keyboard
# ---------------------------------------------------------------------------


class TestSettingsEnginesKeyboard:
    def test_auto_search_engines_menu(self):
        cfg = _mock_chat_config(auto_search_engines=None)
        kb = _settings_engines_keyboard(cfg, "auto_search_engines")
        texts = _button_texts(kb)
        callbacks = _button_callbacks(kb)

        # All best_match engines should appear with ✅ (enabled=None means all on)
        assert any("SauceNAO" in t for t in texts)
        assert any("AnimeTrace" in t for t in texts)
        # All should have the auto_search_engine callback prefix
        assert any(cb.startswith("settings:toggle:auto_search_engine:") for cb in callbacks)
        # Last row should be ← Back
        assert texts[-1] == "← Back"
        assert callbacks[-1] == "settings:back"

    def test_auto_search_engines_some_disabled(self):
        cfg = _mock_chat_config(auto_search_engines=["SauceNAO"])
        kb = _settings_engines_keyboard(cfg, "auto_search_engines")
        texts = _button_texts(kb)

        assert "✅ SauceNAO" in texts
        # Others should be ❌
        assert any("❌" in t and "AnimeTrace" in t for t in texts)

    def test_button_engines_menu_has_best_match_and_link(self):
        cfg = _mock_chat_config(show_best_match=True, show_link=False, button_engines=None)
        kb = _settings_engines_keyboard(cfg, "button_engines")
        texts = _button_texts(kb)
        callbacks = _button_callbacks(kb)

        assert "✅ Best Match" in texts
        assert any("❌" in t and "Go To Image" in t for t in texts)
        assert "settings:toggle:show_best_match" in callbacks
        assert "settings:toggle:show_link" in callbacks

    def test_button_engines_menu_all_engines_present(self):
        cfg = _mock_chat_config(button_engines=None)
        kb = _settings_engines_keyboard(cfg, "button_engines")
        texts = _button_texts(kb)

        # button_engines shows ALL engines (not just best_match_implemented)
        assert any("Google" in t for t in texts)
        assert any("SauceNAO" in t for t in texts)
        assert any("Bing" in t for t in texts)


# ---------------------------------------------------------------------------
# _button_count
# ---------------------------------------------------------------------------


class TestButtonCount:
    def test_all_defaults(self):
        cfg = _mock_chat_config(show_best_match=True, show_link=True, button_engines=None)
        count = _button_count(cfg)
        # 2 (best_match + link) + all engine count
        from reverse_image_search_bot.engines import engines

        assert count == 2 + len(engines)

    def test_excluding_engine(self):
        cfg = _mock_chat_config(show_best_match=True, show_link=True, button_engines=None)
        count_all = _button_count(cfg)
        count_excl = _button_count(cfg, excluding_engine="SauceNAO")
        assert count_excl == count_all - 1

    def test_no_extras(self):
        cfg = _mock_chat_config(show_best_match=False, show_link=False, button_engines=["SauceNAO"])
        assert _button_count(cfg) == 1

    def test_empty_button_engines(self):
        cfg = _mock_chat_config(show_best_match=False, show_link=False, button_engines=[])
        assert _button_count(cfg) == 0

    def test_custom_button_engines(self):
        cfg = _mock_chat_config(show_best_match=True, show_link=False, button_engines=["SauceNAO", "Google"])
        assert _button_count(cfg) == 3  # 1 (best_match) + 2 engines


# ---------------------------------------------------------------------------
# _track_engine_result
# ---------------------------------------------------------------------------


class TestTrackEngineResult:
    def test_found_resets_counter(self):
        cfg = _mock_chat_config(engine_empty_counts={"SauceNAO": 3})
        with patch("reverse_image_search_bot.commands.ChatConfig", return_value=cfg):
            result = _track_engine_result(12345, "SauceNAO", found=True)
            assert result is False
            assert cfg.engine_empty_counts == {}

    def test_not_found_increments(self):
        cfg = _mock_chat_config(engine_empty_counts={})
        with patch("reverse_image_search_bot.commands.ChatConfig", return_value=cfg):
            result = _track_engine_result(12345, "SauceNAO", found=False)
            assert result is False
            assert cfg.engine_empty_counts == {"SauceNAO": 1}

    def test_not_found_below_threshold(self):
        cfg = _mock_chat_config(engine_empty_counts={"SauceNAO": 3})
        with patch("reverse_image_search_bot.commands.ChatConfig", return_value=cfg):
            result = _track_engine_result(12345, "SauceNAO", found=False)
            assert result is False
            assert cfg.engine_empty_counts["SauceNAO"] == 4

    def test_auto_disable_at_threshold(self):
        """After 5 consecutive empty results, engine should be auto-disabled."""
        cfg = _mock_chat_config(
            engine_empty_counts={"SauceNAO": 4},
            auto_search_engines=["SauceNAO", "AnimeTrace", "Trace"],
        )
        with patch("reverse_image_search_bot.commands.ChatConfig", return_value=cfg):
            result = _track_engine_result(12345, "SauceNAO", found=False)
            assert result is True
            assert "SauceNAO" not in cfg.auto_search_engines
            assert cfg.engine_empty_counts["SauceNAO"] == 0

    def test_no_disable_if_last_engine(self):
        """Don't disable the last remaining engine."""
        cfg = _mock_chat_config(
            engine_empty_counts={"SauceNAO": 4},
            auto_search_engines=["SauceNAO"],
        )
        with patch("reverse_image_search_bot.commands.ChatConfig", return_value=cfg):
            result = _track_engine_result(12345, "SauceNAO", found=False)
            assert result is False

    def test_no_disable_if_engine_not_in_list(self):
        """Don't disable an engine that's already not in the active list."""
        cfg = _mock_chat_config(
            engine_empty_counts={"SauceNAO": 4},
            auto_search_engines=["AnimeTrace", "Trace"],
        )
        with patch("reverse_image_search_bot.commands.ChatConfig", return_value=cfg):
            result = _track_engine_result(12345, "SauceNAO", found=False)
            assert result is False

    def test_auto_disable_with_none_engines_uses_relevant(self):
        """When auto_search_engines is None, it defaults to all best_match engines."""
        from reverse_image_search_bot.engines import engines

        relevant = [e.name for e in engines if e.best_match_implemented]
        cfg = _mock_chat_config(
            engine_empty_counts={relevant[0]: 4},
            auto_search_engines=None,
        )
        with patch("reverse_image_search_bot.commands.ChatConfig", return_value=cfg):
            result = _track_engine_result(12345, relevant[0], found=False)
            # Should auto-disable since there are multiple relevant engines
            assert result is True
            assert relevant[0] not in cfg.auto_search_engines


# ---------------------------------------------------------------------------
# build_reply
# ---------------------------------------------------------------------------


class TestBuildReply:
    def test_basic_reply(self):
        result = {"Title": "My Image", "Artist": "Nobody"}
        meta = {
            "provider": "SauceNAO",
            "provider_url": "https://saucenao.com",
        }
        reply, media = build_reply(result, meta)

        assert 'Provided by: <a href="https://saucenao.com"><b >SauceNAO</b></a>' in reply
        assert "<b >Title:</b>" in reply
        assert "<code >My Image</code>" in reply
        assert "<b >Artist:</b>" in reply
        assert "<code >Nobody</code>" in reply
        assert media is None

    def test_with_similarity(self):
        result = {"Title": "Test"}
        meta = {
            "provider": "SauceNAO",
            "provider_url": "https://saucenao.com",
            "similarity": 92.5,
        }
        reply, _media = build_reply(result, meta)
        assert "<b >92.5%</b>" in reply

    def test_with_provided_via(self):
        result = {"Title": "Test"}
        meta = {
            "provider": "SauceNAO",
            "provider_url": "https://saucenao.com",
            "provided_via": "Anilist",
        }
        reply, _media = build_reply(result, meta)
        assert "with <b >Anilist</b>" in reply

    def test_with_provided_via_url(self):
        result = {"Title": "Test"}
        meta = {
            "provider": "SauceNAO",
            "provider_url": "https://saucenao.com",
            "provided_via": "Anilist",
            "provided_via_url": "https://anilist.co",
        }
        reply, _media = build_reply(result, meta)
        assert 'with <a href="https://anilist.co"><b ><b >Anilist</b></b></a>' in reply

    def test_thumbnail_url_becomes_hidden_anchor(self):
        result = {"Title": "Test"}
        meta = {
            "provider": "Test",
            "provider_url": "https://test.com",
            "thumbnail": URL("https://img.test.com/thumb.jpg"),
        }
        reply, media = build_reply(result, meta)
        assert '<a href="https://img.test.com/thumb.jpg">\u200b</a>' in reply
        assert media is None

    def test_thumbnail_list_becomes_media_group(self):
        urls = [URL("https://img.test.com/1.jpg"), URL("https://img.test.com/2.jpg")]
        result = {"Title": "Test"}
        meta = {
            "provider": "Test",
            "provider_url": "https://test.com",
            "thumbnail": urls,
        }
        _reply, media = build_reply(result, meta)
        assert media is not None
        assert len(media) == 2
        assert all(isinstance(m, InputMediaPhoto) for m in media)

    def test_set_value_in_result(self):
        result = {"Tags": {"cat", "dog"}}
        meta = {"provider": "Test", "provider_url": "https://test.com"}
        reply, _media = build_reply(result, meta)
        # Sets are comma-joined (order may vary)
        assert "cat" in reply
        assert "dog" in reply

    def test_list_value_in_result(self):
        result = {"Tags": ["cat", "dog"]}
        meta = {"provider": "Test", "provider_url": "https://test.com"}
        reply, _media = build_reply(result, meta)
        assert "<code >cat</code>" in reply
        assert "<code >dog</code>" in reply

    def test_html_escaping(self):
        result = {"Title": "<script>alert('xss')</script>"}
        meta = {"provider": "Test", "provider_url": "https://test.com"}
        reply, _media = build_reply(result, meta)
        assert "<script>" not in reply
        assert "&lt;script&gt;" in reply


# ---------------------------------------------------------------------------
# _extract_video_frame
# ---------------------------------------------------------------------------


class TestExtractVideoFrame:
    def test_extracts_jpeg_bytes(self, tmp_path):
        """Create a minimal video with moviepy, extract first frame."""
        try:
            from moviepy.video.VideoClip import ColorClip
        except ImportError:
            pytest.skip("moviepy/numpy not available")

        # Create a 1-second red video
        video_path = str(tmp_path / "test.mp4")
        clip = ColorClip(size=(64, 64), color=(255, 0, 0), duration=0.5)
        clip.write_videofile(video_path, fps=10, logger=None)
        clip.close()

        frame_bytes = _extract_video_frame(video_path)
        assert isinstance(frame_bytes, bytes)
        assert len(frame_bytes) > 0
        # JPEG magic bytes
        assert frame_bytes[:2] == b"\xff\xd8"

    def test_invalid_path_raises(self, tmp_path):
        with pytest.raises(OSError):
            _extract_video_frame(str(tmp_path / "nonexistent.mp4"))
