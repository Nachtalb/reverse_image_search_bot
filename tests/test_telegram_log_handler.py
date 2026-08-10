"""Tests for TelegramLogHandler delivery targets (admins vs ERROR_CHAT_ID)."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from reverse_image_search_bot.bot import TelegramLogHandler


@pytest.fixture
def record():
    return logging.LogRecord(
        name="test", level=logging.ERROR, pathname=__file__, lineno=1, msg="boom", args=(), exc_info=None
    )


@pytest.fixture
def handler():
    return TelegramLogHandler(bot=MagicMock(), loop=MagicMock(), level=logging.WARNING)


class TestTelegramLogHandlerTargets:
    @patch("reverse_image_search_bot.bot.asyncio.run_coroutine_threadsafe")
    @patch("reverse_image_search_bot.bot.settings")
    def test_unset_error_chat_sends_to_admins(self, mock_settings, _run, handler, record):
        mock_settings.ERROR_CHAT_ID = None
        mock_settings.ADMIN_IDS = [111, 222]

        handler.emit(record)

        targets = [call.args[0] for call in handler.bot.send_message.call_args_list]
        assert targets == [111, 222]

    @patch("reverse_image_search_bot.bot.asyncio.run_coroutine_threadsafe")
    @patch("reverse_image_search_bot.bot.settings")
    def test_set_error_chat_sends_only_there(self, mock_settings, _run, handler, record):
        mock_settings.ERROR_CHAT_ID = -1004389046822
        mock_settings.ADMIN_IDS = [111, 222]

        handler.emit(record)

        targets = [call.args[0] for call in handler.bot.send_message.call_args_list]
        assert targets == [-1004389046822]

    @patch("reverse_image_search_bot.bot.asyncio.run_coroutine_threadsafe")
    @patch("reverse_image_search_bot.bot.settings")
    def test_long_record_documents_go_to_error_chat(self, mock_settings, _run, handler):
        mock_settings.ERROR_CHAT_ID = -1004389046822
        mock_settings.ADMIN_IDS = [111]
        long_record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname=__file__, lineno=1, msg="x" * 5000, args=(), exc_info=None
        )

        handler.emit(long_record)

        handler.bot.send_message.assert_not_called()
        targets = [call.args[0] for call in handler.bot.send_document.call_args_list]
        assert targets == [-1004389046822]
