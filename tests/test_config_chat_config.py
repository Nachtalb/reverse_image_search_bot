"""Tests for reverse_image_search_bot.config.chat_config."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolated_chat_config():
    """Ensure ChatConfig class state is clean between tests.

    @single_chat replaces ChatConfig with get_instance(), so _loaded_chats
    lives on the original class captured by the closure. We need to access
    it through the closure to verify eviction.
    """
    from reverse_image_search_bot.config.chat_config import ChatConfig

    real_cls = ChatConfig.__closure__[0].cell_contents
    real_cls._loaded_chats = {}
    yield
    real_cls._loaded_chats = {}


class TestChatConfigDefaults:
    def test_private_chat_defaults(self):
        with (
            patch("reverse_image_search_bot.config.chat_config.load_config", return_value=None),
            patch("reverse_image_search_bot.config.chat_config.save_field"),
        ):
            from reverse_image_search_bot.config.chat_config import ChatConfig

            config = ChatConfig(12345)  # positive = private
            assert config.show_buttons is True
            assert config.auto_search_enabled is True
            assert config.onboarded is False

    def test_group_chat_defaults(self):
        """Groups default to buttons and auto_search OFF until onboarded."""
        with (
            patch("reverse_image_search_bot.config.chat_config.load_config", return_value=None),
            patch("reverse_image_search_bot.config.chat_config.save_field"),
        ):
            from reverse_image_search_bot.config.chat_config import ChatConfig

            config = ChatConfig(-100123456)  # negative = group
            assert config.show_buttons is False
            assert config.auto_search_enabled is False

    def test_existing_config_loaded(self):
        """When saved config exists, values override defaults."""
        saved = {"show_buttons": False, "auto_search_enabled": True, "failures_in_a_row": 5}
        with (
            patch("reverse_image_search_bot.config.chat_config.load_config", return_value=saved),
            patch("reverse_image_search_bot.config.chat_config.save_field"),
        ):
            from reverse_image_search_bot.config.chat_config import ChatConfig

            config = ChatConfig(77777)
            assert config.show_buttons is False
            assert config.failures_in_a_row == 5


class TestChatConfigRepr:
    def test_repr(self):
        with (
            patch("reverse_image_search_bot.config.chat_config.load_config", return_value=None),
            patch("reverse_image_search_bot.config.chat_config.save_field"),
        ):
            from reverse_image_search_bot.config.chat_config import ChatConfig

            config = ChatConfig(99999)
            assert repr(config) == "<ChatConfig(chat_id=99999)>"


class TestChatConfigSetattr:
    def test_setting_config_field_saves(self):
        with (
            patch("reverse_image_search_bot.config.chat_config.load_config", return_value=None),
            patch("reverse_image_search_bot.config.chat_config.save_field") as mock_save,
        ):
            from reverse_image_search_bot.config.chat_config import ChatConfig

            config = ChatConfig(33333)
            config.show_buttons = False
            mock_save.assert_called_with(33333, "show_buttons", False)
            assert config.show_buttons is False


class TestResetEngineCounter:
    def test_reset_removes_engine(self):
        with (
            patch("reverse_image_search_bot.config.chat_config.load_config", return_value=None),
            patch("reverse_image_search_bot.config.chat_config.save_field"),
        ):
            from reverse_image_search_bot.config.chat_config import ChatConfig

            config = ChatConfig(44444)
            config.engine_empty_counts = {"SauceNAO": 3, "Yandex": 1}
            config.reset_engine_counter("SauceNAO")
            assert "SauceNAO" not in config.engine_empty_counts
            assert config.engine_empty_counts["Yandex"] == 1


class TestSingleChatDecorator:
    def test_fifo_eviction(self):
        """Cache evicts oldest entry when exceeding 500."""
        with (
            patch("reverse_image_search_bot.config.chat_config.load_config", return_value=None),
            patch("reverse_image_search_bot.config.chat_config.save_field"),
        ):
            from reverse_image_search_bot.config.chat_config import ChatConfig

            real_cls = ChatConfig.__closure__[0].cell_contents
            real_cls._loaded_chats = {}

            for idx in range(500):
                ChatConfig(20000 + idx)

            assert len(real_cls._loaded_chats) == 500
            assert 20000 in real_cls._loaded_chats

            ChatConfig(20500)
            assert len(real_cls._loaded_chats) == 500
            assert 20000 not in real_cls._loaded_chats
            assert 20500 in real_cls._loaded_chats

    def test_same_id_returns_cached(self):
        with (
            patch("reverse_image_search_bot.config.chat_config.load_config", return_value=None),
            patch("reverse_image_search_bot.config.chat_config.save_field"),
        ):
            from reverse_image_search_bot.config.chat_config import ChatConfig

            c1 = ChatConfig(55555)
            c2 = ChatConfig(55555)
            assert c1 is c2

    def test_loaded_chats_created_if_missing(self):
        """Cover the hasattr guard in single_chat.get_instance."""
        with (
            patch("reverse_image_search_bot.config.chat_config.load_config", return_value=None),
            patch("reverse_image_search_bot.config.chat_config.save_field"),
        ):
            from reverse_image_search_bot.config.chat_config import ChatConfig

            real_cls = ChatConfig.__closure__[0].cell_contents
            # Delete _loaded_chats to trigger the hasattr branch
            if hasattr(real_cls, "_loaded_chats"):
                delattr(real_cls, "_loaded_chats")

            config = ChatConfig(66666)
            assert config is not None
            assert hasattr(real_cls, "_loaded_chats")
