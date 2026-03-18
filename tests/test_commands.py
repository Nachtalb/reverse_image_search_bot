"""Tests for pure functions in reverse_image_search_bot.commands."""

from unittest.mock import AsyncMock, MagicMock, patch

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
    callback_query_handler,
    file_handler,
    settings_callback_handler,
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
        with patch("reverse_image_search_bot.commands.search.ChatConfig", return_value=cfg):
            result = _track_engine_result(12345, "SauceNAO", found=True)
            assert result is False
            assert cfg.engine_empty_counts == {}

    def test_not_found_increments(self):
        cfg = _mock_chat_config(engine_empty_counts={})
        with patch("reverse_image_search_bot.commands.search.ChatConfig", return_value=cfg):
            result = _track_engine_result(12345, "SauceNAO", found=False)
            assert result is False
            assert cfg.engine_empty_counts == {"SauceNAO": 1}

    def test_not_found_below_threshold(self):
        cfg = _mock_chat_config(engine_empty_counts={"SauceNAO": 3})
        with patch("reverse_image_search_bot.commands.search.ChatConfig", return_value=cfg):
            result = _track_engine_result(12345, "SauceNAO", found=False)
            assert result is False
            assert cfg.engine_empty_counts["SauceNAO"] == 4

    def test_auto_disable_at_threshold(self):
        """After 5 consecutive empty results, engine should be auto-disabled."""
        cfg = _mock_chat_config(
            engine_empty_counts={"SauceNAO": 4},
            auto_search_engines=["SauceNAO", "AnimeTrace", "Trace"],
        )
        with patch("reverse_image_search_bot.commands.search.ChatConfig", return_value=cfg):
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
        with patch("reverse_image_search_bot.commands.search.ChatConfig", return_value=cfg):
            result = _track_engine_result(12345, "SauceNAO", found=False)
            assert result is False

    def test_no_disable_if_engine_not_in_list(self):
        """Don't disable an engine that's already not in the active list."""
        cfg = _mock_chat_config(
            engine_empty_counts={"SauceNAO": 4},
            auto_search_engines=["AnimeTrace", "Trace"],
        )
        with patch("reverse_image_search_bot.commands.search.ChatConfig", return_value=cfg):
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
        with patch("reverse_image_search_bot.commands.search.ChatConfig", return_value=cfg):
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
        assert "92.5% similarity" in reply

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
        assert '<a href="https://anilist.co"><b >Anilist</b></a>' in reply

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


# ---------------------------------------------------------------------------
# Mock helpers for Telegram objects
# ---------------------------------------------------------------------------


def _mock_update(
    chat_id=12345,
    chat_type="private",
    user_id=99999,
    callback_data=None,
    attachment=None,
    message_text=None,
):
    """Build a mock Update with the common structure."""
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_chat.type = chat_type
    update.effective_user.id = user_id

    message = MagicMock()
    message.chat_id = chat_id
    message.from_user.id = user_id
    message.from_user.language_code = "en"
    message.reply_text = AsyncMock()
    message.reply_html = AsyncMock()
    message.effective_attachment = attachment

    update.effective_message = message
    update.message = message

    if callback_data is not None:
        query = MagicMock()
        query.data = callback_data
        query.answer = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
    else:
        update.callback_query = None

    return update


def _mock_context(banned_users=None):
    context = MagicMock()
    context.bot_data = {"banned_users": banned_users or []}
    context.bot.send_chat_action = AsyncMock()
    context.bot.get_chat_member = AsyncMock()
    return context


# ---------------------------------------------------------------------------
# settings_callback_handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSettingsCallbackHandler:
    async def test_noop(self):
        update = _mock_update(callback_data="settings:noop")
        context = _mock_context()
        await settings_callback_handler(update, context)
        update.callback_query.answer.assert_awaited_once_with()

    async def test_disabled_auto_search_engines(self):
        update = _mock_update(callback_data="settings:disabled:auto_search_engines")
        context = _mock_context()
        await settings_callback_handler(update, context)
        update.callback_query.answer.assert_awaited_once_with(
            "Enable auto-search first to configure its engines.", show_alert=False
        )

    async def test_disabled_button_engines(self):
        update = _mock_update(callback_data="settings:disabled:button_engines")
        context = _mock_context()
        await settings_callback_handler(update, context)
        update.callback_query.answer.assert_awaited_once_with(
            'Enable "Show buttons" first to configure engine buttons.', show_alert=False
        )

    async def test_toggle_auto_search_on_off(self):
        cfg = _mock_chat_config(auto_search_enabled=True, show_buttons=True)
        update = _mock_update(callback_data="settings:toggle:auto_search")
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.settings._is_settings_allowed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("reverse_image_search_bot.commands.settings.ChatConfig", return_value=cfg),
        ):
            await settings_callback_handler(update, context)
            assert cfg.auto_search_enabled is False
            update.callback_query.edit_message_reply_markup.assert_awaited_once()

    async def test_toggle_auto_search_blocked_in_private(self):
        """In private chat, can't disable auto_search if show_buttons is also off."""
        cfg = _mock_chat_config(auto_search_enabled=True, show_buttons=False)
        update = _mock_update(callback_data="settings:toggle:auto_search", chat_id=12345)
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.settings._is_settings_allowed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("reverse_image_search_bot.commands.settings.ChatConfig", return_value=cfg),
        ):
            await settings_callback_handler(update, context)
            update.callback_query.answer.assert_any_await(
                "⚠️ Enable engine buttons first — at least one must be active.", show_alert=True
            )
            # Should NOT have toggled
            assert cfg.auto_search_enabled is True

    async def test_toggle_show_buttons_blocked_in_private(self):
        """In private chat, can't disable show_buttons if auto_search is also off."""
        cfg = _mock_chat_config(auto_search_enabled=False, show_buttons=True)
        update = _mock_update(callback_data="settings:toggle:show_buttons", chat_id=12345)
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.settings._is_settings_allowed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("reverse_image_search_bot.commands.settings.ChatConfig", return_value=cfg),
        ):
            await settings_callback_handler(update, context)
            update.callback_query.answer.assert_any_await(
                "⚠️ Enable auto-search first — at least one must be active.", show_alert=True
            )
            assert cfg.show_buttons is True

    async def test_toggle_show_best_match_off(self):
        cfg = _mock_chat_config(show_best_match=True, show_link=True, button_engines=["SauceNAO"])
        update = _mock_update(callback_data="settings:toggle:show_best_match")
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.settings._is_settings_allowed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("reverse_image_search_bot.commands.settings.ChatConfig", return_value=cfg),
        ):
            await settings_callback_handler(update, context)
            assert cfg.show_best_match is False

    async def test_toggle_show_best_match_blocked_last_button(self):
        """Can't disable best_match if it's the only active button."""
        cfg = _mock_chat_config(show_best_match=True, show_link=False, button_engines=[])
        update = _mock_update(callback_data="settings:toggle:show_best_match")
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.settings._is_settings_allowed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("reverse_image_search_bot.commands.settings.ChatConfig", return_value=cfg),
        ):
            await settings_callback_handler(update, context)
            update.callback_query.answer.assert_any_await("⚠️ At least one button must stay enabled.", show_alert=True)
            assert cfg.show_best_match is True

    async def test_toggle_show_link(self):
        cfg = _mock_chat_config(show_link=True, show_best_match=True, button_engines=["SauceNAO"])
        update = _mock_update(callback_data="settings:toggle:show_link")
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.settings._is_settings_allowed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("reverse_image_search_bot.commands.settings.ChatConfig", return_value=cfg),
        ):
            await settings_callback_handler(update, context)
            assert cfg.show_link is False

    async def test_toggle_auto_search_engine(self):
        cfg = _mock_chat_config(auto_search_engines=["SauceNAO", "AnimeTrace"])
        update = _mock_update(callback_data="settings:toggle:auto_search_engine:SauceNAO")
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.settings._is_settings_allowed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("reverse_image_search_bot.commands.settings.ChatConfig", return_value=cfg),
        ):
            await settings_callback_handler(update, context)
            assert "SauceNAO" not in cfg.auto_search_engines

    async def test_toggle_auto_search_engine_last_blocked(self):
        cfg = _mock_chat_config(auto_search_engines=["SauceNAO"])
        update = _mock_update(callback_data="settings:toggle:auto_search_engine:SauceNAO")
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.settings._is_settings_allowed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("reverse_image_search_bot.commands.settings.ChatConfig", return_value=cfg),
        ):
            await settings_callback_handler(update, context)
            update.callback_query.answer.assert_any_await("⚠️ At least one engine must stay enabled.", show_alert=True)
            assert "SauceNAO" in cfg.auto_search_engines

    async def test_toggle_auto_search_engine_re_enable(self):
        cfg = _mock_chat_config(auto_search_engines=["AnimeTrace"])
        cfg.reset_engine_counter = MagicMock()
        update = _mock_update(callback_data="settings:toggle:auto_search_engine:SauceNAO")
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.settings._is_settings_allowed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("reverse_image_search_bot.commands.settings.ChatConfig", return_value=cfg),
        ):
            await settings_callback_handler(update, context)
            cfg.reset_engine_counter.assert_called_once_with("SauceNAO")

    async def test_toggle_button_engine_disable(self):
        cfg = _mock_chat_config(show_best_match=True, show_link=True, button_engines=["SauceNAO", "Google"])
        update = _mock_update(callback_data="settings:toggle:button_engine:SauceNAO")
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.settings._is_settings_allowed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("reverse_image_search_bot.commands.settings.ChatConfig", return_value=cfg),
        ):
            await settings_callback_handler(update, context)
            assert "SauceNAO" not in cfg.button_engines

    async def test_toggle_button_engine_blocked_last(self):
        """Can't disable engine if it would leave 0 buttons."""
        cfg = _mock_chat_config(show_best_match=False, show_link=False, button_engines=["SauceNAO"])
        update = _mock_update(callback_data="settings:toggle:button_engine:SauceNAO")
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.settings._is_settings_allowed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("reverse_image_search_bot.commands.settings.ChatConfig", return_value=cfg),
        ):
            await settings_callback_handler(update, context)
            update.callback_query.answer.assert_any_await("⚠️ At least one button must stay enabled.", show_alert=True)

    async def test_menu_action(self):
        cfg = _mock_chat_config()
        update = _mock_update(callback_data="settings:menu:auto_search_engines")
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.settings._is_settings_allowed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("reverse_image_search_bot.commands.settings.ChatConfig", return_value=cfg),
        ):
            await settings_callback_handler(update, context)
            update.callback_query.edit_message_reply_markup.assert_awaited_once()

    async def test_back_action(self):
        cfg = _mock_chat_config()
        update = _mock_update(callback_data="settings:back")
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.settings._is_settings_allowed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("reverse_image_search_bot.commands.settings.ChatConfig", return_value=cfg),
        ):
            await settings_callback_handler(update, context)
            update.callback_query.edit_message_text.assert_awaited_once()

    async def test_not_allowed_in_group(self):
        update = _mock_update(callback_data="settings:toggle:auto_search", chat_type="group", chat_id=-100123)
        context = _mock_context()

        with patch(
            "reverse_image_search_bot.commands.settings._is_settings_allowed",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await settings_callback_handler(update, context)
            update.callback_query.answer.assert_any_await("Only group admins can change settings.", show_alert=True)


# ---------------------------------------------------------------------------
# callback_query_handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCallbackQueryHandler:
    async def test_noop(self):
        update = _mock_update(callback_data="noop")
        context = _mock_context()
        await callback_query_handler(update, context)
        update.callback_query.answer.assert_awaited_once()

    async def test_unknown_command(self):
        update = _mock_update(callback_data="something_unknown")
        context = _mock_context()
        await callback_query_handler(update, context)
        update.callback_query.answer.assert_awaited_once_with("Something went wrong")

    async def test_best_match_dispatches(self):
        update = _mock_update(callback_data="best_match https://example.com/img.jpg")
        context = _mock_context()

        with patch("reverse_image_search_bot.commands.handlers.best_match", new_callable=AsyncMock) as mock_bm:
            await callback_query_handler(update, context)
            mock_bm.assert_awaited_once_with(update, context, "https://example.com/img.jpg")

    async def test_wait_for_dispatches(self):
        update = _mock_update(callback_data="wait_for SauceNAO")
        context = _mock_context()

        with patch("reverse_image_search_bot.commands.handlers.send_wait_for", new_callable=AsyncMock) as mock_wf:
            await callback_query_handler(update, context)
            mock_wf.assert_awaited_once_with(update, context, "SauceNAO")


# ---------------------------------------------------------------------------
# file_handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFileHandler:
    async def test_no_message_returns(self):
        update = _mock_update()
        update.effective_message = None
        context = _mock_context()
        await file_handler(update, context, message=None)
        # No crash, no reply

    async def test_no_user_returns(self):
        update = _mock_update()
        update.effective_message.from_user = None
        context = _mock_context()
        await file_handler(update, context)
        # No crash, no reply

    async def test_banned_user_rejected(self):
        update = _mock_update(user_id=666)
        context = _mock_context(banned_users=[666])
        await file_handler(update, context)
        update.effective_message.reply_text.assert_awaited_once()
        assert "banned" in update.effective_message.reply_text.call_args[0][0].lower()

    async def test_photo_attachment_triggers_search(self):
        from telegram import PhotoSize

        photo = MagicMock(spec=PhotoSize)
        photo.file_size = 1000
        photo.file_unique_id = "test123"

        update = _mock_update(attachment=photo)
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.search.image_to_url",
                new_callable=AsyncMock,
                return_value=URL("https://ris-test-uploads.naa.gg/test123.jpg"),
            ),
            patch("reverse_image_search_bot.commands.search.general_image_search", new_callable=AsyncMock),
            patch("reverse_image_search_bot.commands.search.best_match", new_callable=AsyncMock) as mock_bm,
            patch("reverse_image_search_bot.commands.search.ChatConfig") as mock_cc,
        ):
            mock_cc.return_value = _mock_chat_config(auto_search_enabled=True)
            await file_handler(update, context)
            # Should have called best_match (auto_search enabled)
            mock_bm.assert_awaited_once()

    async def test_photo_auto_search_disabled_only_general(self):
        from telegram import PhotoSize

        photo = MagicMock(spec=PhotoSize)
        photo.file_size = 1000
        photo.file_unique_id = "test456"

        update = _mock_update(attachment=photo)
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.search.image_to_url",
                new_callable=AsyncMock,
                return_value=URL("https://ris-test-uploads.naa.gg/test456.jpg"),
            ),
            patch("reverse_image_search_bot.commands.search.general_image_search", new_callable=AsyncMock),
            patch("reverse_image_search_bot.commands.search.best_match", new_callable=AsyncMock) as mock_bm,
            patch("reverse_image_search_bot.commands.search.ChatConfig") as mock_cc,
        ):
            mock_cc.return_value = _mock_chat_config(auto_search_enabled=False)
            await file_handler(update, context)
            # Should NOT have called best_match
            mock_bm.assert_not_awaited()

    async def test_unsupported_format(self):
        attachment = MagicMock()
        attachment.file_size = 100
        # Not a recognized type
        type(attachment).__name__ = "UnknownType"

        update = _mock_update(attachment=attachment)
        context = _mock_context()

        await file_handler(update, context)
        update.effective_message.reply_text.assert_awaited()
        assert "not supported" in update.effective_message.reply_text.call_args[0][0].lower()

    async def test_video_attachment_triggers_video_to_url(self):
        from telegram import Video

        video = MagicMock(spec=Video)
        video.file_size = 5000
        video.file_unique_id = "vid789"
        video.mime_type = "video/mp4"

        update = _mock_update(attachment=video)
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.search.video_to_url",
                new_callable=AsyncMock,
                return_value=URL("https://ris-test-uploads.naa.gg/vid789.jpg"),
            ) as mock_vtu,
            patch("reverse_image_search_bot.commands.search.general_image_search", new_callable=AsyncMock),
            patch("reverse_image_search_bot.commands.search.best_match", new_callable=AsyncMock),
            patch("reverse_image_search_bot.commands.search.ChatConfig") as mock_cc,
        ):
            mock_cc.return_value = _mock_chat_config(auto_search_enabled=True)
            await file_handler(update, context)
            mock_vtu.assert_awaited_once_with(video)

    async def test_animated_sticker_rejected(self):
        from telegram import Sticker

        sticker = MagicMock(spec=Sticker)
        sticker.file_size = 500
        sticker.file_unique_id = "stk001"
        sticker.is_video = False
        sticker.is_animated = True
        sticker.mime_type = None

        update = _mock_update(attachment=sticker)
        context = _mock_context()

        await file_handler(update, context)
        update.effective_message.reply_text.assert_awaited()
        assert "animated" in update.effective_message.reply_text.call_args[0][0].lower()

    async def test_list_attachment_uses_last(self):
        """When attachment is a list (e.g. PhotoSize[]), use the last (largest)."""
        from telegram import PhotoSize

        small = MagicMock(spec=PhotoSize)
        small.file_size = 100
        small.file_unique_id = "small"

        large = MagicMock(spec=PhotoSize)
        large.file_size = 5000
        large.file_unique_id = "large"

        update = _mock_update(attachment=[small, large])
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.search.image_to_url",
                new_callable=AsyncMock,
                return_value=URL("https://ris-test-uploads.naa.gg/large.jpg"),
            ) as mock_itu,
            patch("reverse_image_search_bot.commands.search.general_image_search", new_callable=AsyncMock),
            patch("reverse_image_search_bot.commands.search.best_match", new_callable=AsyncMock),
            patch("reverse_image_search_bot.commands.search.ChatConfig") as mock_cc,
        ):
            mock_cc.return_value = _mock_chat_config(auto_search_enabled=True)
            await file_handler(update, context)
            mock_itu.assert_awaited_once_with(large)

    async def test_error_in_search_replies_error(self):
        from telegram import PhotoSize

        photo = MagicMock(spec=PhotoSize)
        photo.file_size = 1000
        photo.file_unique_id = "err001"

        update = _mock_update(attachment=photo)
        context = _mock_context()

        with (
            patch(
                "reverse_image_search_bot.commands.search.image_to_url",
                new_callable=AsyncMock,
                return_value=URL("https://ris-test-uploads.naa.gg/err001.jpg"),
            ),
            patch("reverse_image_search_bot.commands.search.general_image_search", new_callable=AsyncMock),
            patch(
                "reverse_image_search_bot.commands.search.best_match",
                new_callable=AsyncMock,
                side_effect=RuntimeError("engine exploded"),
            ),
            patch("reverse_image_search_bot.commands.search.ChatConfig") as mock_cc,
        ):
            mock_cc.return_value = _mock_chat_config(auto_search_enabled=True)
            with pytest.raises(RuntimeError, match="engine exploded"):
                await file_handler(update, context)
            # Should have sent error message before re-raising
            update.effective_message.reply_text.assert_awaited()
            assert "error" in update.effective_message.reply_text.call_args[0][0].lower()
