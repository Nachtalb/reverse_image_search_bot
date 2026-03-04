"""Tests for bot command registration on startup."""

from unittest.mock import AsyncMock, patch

import pytest
from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from reverse_image_search_bot.bot import (
    _ADMIN_COMMANDS,
    _LOCALISED_COMMANDS,
    _PUBLIC_COMMANDS,
    _set_bot_commands,
)


@pytest.fixture
def mock_app():
    app = AsyncMock()
    app.bot.set_my_commands = AsyncMock()
    return app


class TestCommandDefinitions:
    def test_public_commands_not_empty(self):
        assert len(_PUBLIC_COMMANDS) > 0

    def test_admin_commands_superset_of_public(self):
        public_names = {c.command for c in _PUBLIC_COMMANDS}
        admin_names = {c.command for c in _ADMIN_COMMANDS}
        assert public_names.issubset(admin_names)

    def test_admin_has_ban_and_id(self):
        admin_names = {c.command for c in _ADMIN_COMMANDS}
        assert "ban" in admin_names
        assert "id" in admin_names

    def test_public_does_not_have_admin_commands(self):
        public_names = {c.command for c in _PUBLIC_COMMANDS}
        assert "ban" not in public_names
        assert "id" not in public_names

    def test_all_commands_are_bot_command_instances(self):
        for cmd in _PUBLIC_COMMANDS + _ADMIN_COMMANDS:
            assert isinstance(cmd, BotCommand)


class TestSetBotCommands:
    @pytest.mark.asyncio
    @patch("reverse_image_search_bot.bot.settings")
    async def test_sets_default_scope(self, mock_settings, mock_app):
        mock_settings.ADMIN_IDS = []
        await _set_bot_commands(mock_app)
        mock_app.bot.set_my_commands.assert_any_call(_PUBLIC_COMMANDS, scope=BotCommandScopeDefault())

    @pytest.mark.asyncio
    @patch("reverse_image_search_bot.bot.settings")
    async def test_sets_localised_commands(self, mock_settings, mock_app):
        mock_settings.ADMIN_IDS = []
        await _set_bot_commands(mock_app)
        for lang, commands in _LOCALISED_COMMANDS.items():
            mock_app.bot.set_my_commands.assert_any_call(
                commands, scope=BotCommandScopeDefault(), language_code=lang
            )
        # 1 default + N localised + 0 admin
        assert mock_app.bot.set_my_commands.call_count == 1 + len(_LOCALISED_COMMANDS)

    @pytest.mark.asyncio
    @patch("reverse_image_search_bot.bot.settings")
    async def test_sets_admin_scope_per_admin(self, mock_settings, mock_app):
        mock_settings.ADMIN_IDS = [111, 222]
        await _set_bot_commands(mock_app)
        mock_app.bot.set_my_commands.assert_any_call(_ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=111))
        mock_app.bot.set_my_commands.assert_any_call(_ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=222))
        # 1 default + N localised + 2 admin
        assert mock_app.bot.set_my_commands.call_count == 1 + len(_LOCALISED_COMMANDS) + 2

    @pytest.mark.asyncio
    @patch("reverse_image_search_bot.bot.settings")
    async def test_admin_failure_does_not_crash(self, mock_settings, mock_app):
        mock_settings.ADMIN_IDS = [111]
        # 1 default + N localised succeed, then admin fails
        side_effects: list[bool | Exception] = [True] * (1 + len(_LOCALISED_COMMANDS)) + [Exception("chat not found")]
        mock_app.bot.set_my_commands = AsyncMock(side_effect=side_effects)
        # Should not raise
        await _set_bot_commands(mock_app)

    @pytest.mark.asyncio
    @patch("reverse_image_search_bot.bot.settings")
    async def test_localised_failure_does_not_crash(self, mock_settings, mock_app):
        mock_settings.ADMIN_IDS = []
        # Default succeeds, first localised fails, rest succeed
        side_effects: list[bool | Exception] = [True, Exception("lang fail")] + [True] * (len(_LOCALISED_COMMANDS) - 1)
        mock_app.bot.set_my_commands = AsyncMock(side_effect=side_effects)
        # Should not raise
        await _set_bot_commands(mock_app)
