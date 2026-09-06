"""The /history command and the Mini App menu button."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Update

from reverse_image_search_bot.commands import history as mod


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(mod.settings, "WEBAPP_ENABLED", True)
    monkeypatch.setattr(mod.settings, "REPORT_BASE_URL", "https://ris.example")


def _update(chat_type="private"):
    update = MagicMock(spec=Update)
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    update.effective_chat = MagicMock()
    update.effective_chat.type = chat_type
    update.effective_chat.id = 7
    update.effective_user = MagicMock(id=7, language_code="en")
    return update


class TestWebappUrl:
    def test_none_when_disabled(self, monkeypatch):
        monkeypatch.setattr(mod.settings, "WEBAPP_ENABLED", False)
        monkeypatch.setattr(mod.settings, "REPORT_BASE_URL", "https://ris.example")
        assert mod.webapp_url() is None

    def test_none_without_a_base_url(self, monkeypatch):
        """Enabled but unreachable is not configured — do not offer a broken button."""
        monkeypatch.setattr(mod.settings, "WEBAPP_ENABLED", True)
        monkeypatch.setattr(mod.settings, "REPORT_BASE_URL", "")
        assert mod.webapp_url() is None

    def test_built_from_the_base_url(self, configured):
        assert mod.webapp_url() == "https://ris.example/app"


class TestHistoryCommand:
    async def test_offers_a_web_app_button(self, configured):
        update = _update()
        await mod.history_command(update, MagicMock())
        kwargs = update.effective_message.reply_text.call_args.kwargs
        button = kwargs["reply_markup"].inline_keyboard[0][0]
        assert button.web_app.url == "https://ris.example/app"

    async def test_says_so_when_not_configured(self, monkeypatch):
        monkeypatch.setattr(mod.settings, "WEBAPP_ENABLED", False)
        update = _update()
        await mod.history_command(update, MagicMock())
        assert update.effective_message.reply_text.call_args.kwargs.get("reply_markup") is None

    async def test_declines_in_groups(self, configured):
        """Telegram only allows web_app buttons in private chats."""
        update = _update(chat_type="supergroup")
        await mod.history_command(update, MagicMock())
        assert update.effective_message.reply_text.call_args.kwargs.get("reply_markup") is None

    async def test_survives_an_edited_message_update(self, configured):
        """Handlers also fire on edits, where effective_message can be absent."""
        update = MagicMock(spec=Update)
        update.effective_message = None
        update.effective_chat = MagicMock()
        await mod.history_command(update, MagicMock())  # must not raise


class TestMenuButton:
    async def test_sets_the_default_button_when_configured(self, configured):
        from reverse_image_search_bot import bot as botmod

        app = MagicMock()
        app.bot.set_chat_menu_button = AsyncMock()
        await botmod._set_webapp_menu_button(app)
        menu = app.bot.set_chat_menu_button.call_args.kwargs["menu_button"]
        assert menu.web_app.url == "https://ris.example/app"

    async def test_does_nothing_when_not_configured(self, monkeypatch):
        from reverse_image_search_bot import bot as botmod

        monkeypatch.setattr(mod.settings, "WEBAPP_ENABLED", False)
        app = MagicMock()
        app.bot.set_chat_menu_button = AsyncMock()
        await botmod._set_webapp_menu_button(app)
        app.bot.set_chat_menu_button.assert_not_called()

    async def test_a_telegram_failure_does_not_break_startup(self, configured):
        from reverse_image_search_bot import bot as botmod

        app = MagicMock()
        app.bot.set_chat_menu_button = AsyncMock(side_effect=RuntimeError("nope"))
        await botmod._set_webapp_menu_button(app)  # must not raise
