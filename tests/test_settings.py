"""Tests for reverse_image_search_bot.settings — env var parsing."""

import os
from unittest.mock import patch

import pytest


class TestRequiredEnv:
    def test_missing_env_raises(self):
        from reverse_image_search_bot.settings import required_env

        with patch.dict(os.environ, {}, clear=False):
            # Ensure the var doesn't exist
            os.environ.pop("__TEST_MISSING_VAR__", None)
            with pytest.raises(ValueError, match="Missing required environment variable"):
                required_env("__TEST_MISSING_VAR__")

    def test_empty_env_raises(self):
        from reverse_image_search_bot.settings import required_env

        with (
            patch.dict(os.environ, {"__TEST_EMPTY_VAR__": ""}),
            pytest.raises(ValueError, match="Missing required environment variable"),
        ):
            required_env("__TEST_EMPTY_VAR__")

    def test_present_env_returns_value(self):
        from reverse_image_search_bot.settings import required_env

        with patch.dict(os.environ, {"__TEST_PRESENT__": "hello"}):
            assert required_env("__TEST_PRESENT__") == "hello"


class TestGetEnvList:
    def test_comma_separated(self):
        from reverse_image_search_bot.settings import get_env_list

        with patch.dict(os.environ, {"__TEST_LIST__": "1,2,3"}):
            assert get_env_list("__TEST_LIST__") == [1, 2, 3]

    def test_empty(self):
        from reverse_image_search_bot.settings import get_env_list

        with patch.dict(os.environ, {"__TEST_LIST__": ""}):
            assert get_env_list("__TEST_LIST__") == []

    def test_missing(self):
        from reverse_image_search_bot.settings import get_env_list

        os.environ.pop("__TEST_MISSING_LIST__", None)
        assert get_env_list("__TEST_MISSING_LIST__") == []

    def test_non_numeric_filtered(self):
        from reverse_image_search_bot.settings import get_env_list

        with patch.dict(os.environ, {"__TEST_LIST__": "1,abc,3"}):
            assert get_env_list("__TEST_LIST__") == [1, 3]


class TestUploaderConfig:
    def test_local_uploader_loaded(self):
        """Default test env uses local uploader."""
        from reverse_image_search_bot import settings

        assert settings.UPLOADER["uploader"] == "local"
        assert "path" in settings.UPLOADER["configuration"]

    def test_ssh_uploader_config(self):
        """SSH uploader branch requires specific env vars."""
        env = {
            "TELEGRAM_API_TOKEN": "test:token",
            "UPLOADER_TYPE": "ssh",
            "UPLOADER_HOST": "ssh.example.com",
            "UPLOADER_USER": "deploy",
            "UPLOADER_PASSWORD": "secret",
            "UPLOADER_UPLOAD_DIR": "/var/uploads",
            "UPLOADER_URL": "https://uploads.example.com",
            "SAUCENAO_API": "test",
            "TRACE_API": "test",
        }
        # We can't re-import settings easily, but we can test the logic directly
        from reverse_image_search_bot.settings import required_env

        with patch.dict(os.environ, env, clear=False):
            assert required_env("UPLOADER_HOST") == "ssh.example.com"
            assert required_env("UPLOADER_USER") == "deploy"
            assert required_env("UPLOADER_PASSWORD") == "secret"
            assert required_env("UPLOADER_UPLOAD_DIR") == "/var/uploads"


class TestModeConfig:
    def test_default_mode_is_polling(self):
        from reverse_image_search_bot import settings

        assert settings.MODE_ACTIVE == "polling"
        assert settings.MODE["active"] == "polling"

    def test_webhook_mode_branch(self):
        """Re-import settings with webhook mode to cover that branch."""
        import importlib
        import sys

        env = {
            "TELEGRAM_API_TOKEN": "test:token",
            "UPLOADER_PATH": "/tmp/ris_test_uploads",
            "UPLOADER_URL": "https://ris-test-uploads.naa.gg",
            "SAUCENAO_API": "test-key",
            "TRACE_API": "test-key",
            "MODE_ACTIVE": "webhook",
            "MODE_LISTEN": "0.0.0.0",
            "MODE_PORT": "8443",
            "MODE_URL_PATH": "/webhook",
            "MODE_WEBHOOK_URL": "https://bot.example.com/webhook",
        }
        with patch.dict(os.environ, env, clear=False):
            # Remove cached module to force re-import
            mod_name = "reverse_image_search_bot.settings"
            saved = sys.modules.pop(mod_name, None)
            try:
                mod = importlib.import_module(mod_name)
                assert mod.MODE_ACTIVE == "webhook"
                assert mod.MODE["configuration"]["listen"] == "0.0.0.0"
                assert mod.MODE["configuration"]["port"] == 8443
                assert mod.MODE["configuration"]["url_path"] == "/webhook"
            finally:
                # Restore original module
                sys.modules.pop(mod_name, None)
                if saved:
                    sys.modules[mod_name] = saved

    def test_ssh_uploader_branch(self):
        """Re-import settings with SSH uploader to cover that branch."""
        import importlib
        import sys

        env = {
            "TELEGRAM_API_TOKEN": "test:token",
            "UPLOADER_TYPE": "ssh",
            "UPLOADER_HOST": "ssh.naa.gg",
            "UPLOADER_USER": "deploy",
            "UPLOADER_PASSWORD": "secret",
            "UPLOADER_UPLOAD_DIR": "/var/uploads",
            "UPLOADER_URL": "https://uploads.naa.gg",
            "SAUCENAO_API": "test-key",
            "TRACE_API": "test-key",
        }
        with patch.dict(os.environ, env, clear=False):
            mod_name = "reverse_image_search_bot.settings"
            saved = sys.modules.pop(mod_name, None)
            try:
                mod = importlib.import_module(mod_name)
                assert mod.UPLOADER["uploader"] == "ssh"
                assert mod.UPLOADER["configuration"]["host"] == "ssh.naa.gg"
                assert mod.UPLOADER["configuration"]["user"] == "deploy"
            finally:
                sys.modules.pop(mod_name, None)
                if saved:
                    sys.modules[mod_name] = saved
