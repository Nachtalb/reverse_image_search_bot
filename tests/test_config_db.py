"""Tests for reverse_image_search_bot.config.db — uses temp SQLite."""

import contextlib
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# We need to patch CONFIG_DB_PATH before importing db module functions
_tmp_dir = tempfile.mkdtemp()
_tmp_db = Path(_tmp_dir) / "test_config.db"


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path):
    """Give each test a fresh DB by patching CONFIG_DB_PATH and clearing thread-local."""
    db_path = tmp_path / "config.db"
    with patch("reverse_image_search_bot.config.db.CONFIG_DB_PATH", db_path):
        # Clear thread-local connection so it reconnects to new path
        import reverse_image_search_bot.config.db as db_mod

        if hasattr(db_mod._local, "conn"):
            with contextlib.suppress(Exception):
                db_mod._local.conn.close()
            del db_mod._local.conn
        yield db_path


class TestToPython:
    def test_bool_fields(self):
        from reverse_image_search_bot.config.db import _to_python

        assert _to_python("show_buttons", 1) is True
        assert _to_python("show_buttons", 0) is False

    def test_json_fields(self):
        from reverse_image_search_bot.config.db import _to_python

        assert _to_python("auto_search_engines", '["SauceNAO", "Google"]') == ["SauceNAO", "Google"]
        assert _to_python("button_engines", None) is None

    def test_engine_empty_counts_default(self):
        from reverse_image_search_bot.config.db import _to_python

        assert _to_python("engine_empty_counts", None) == {}

    def test_integer_field(self):
        from reverse_image_search_bot.config.db import _to_python

        assert _to_python("failures_in_a_row", 5) == 5


class TestToSql:
    def test_bool_to_int(self):
        from reverse_image_search_bot.config.db import _to_sql

        assert _to_sql("show_buttons", True) == 1
        assert _to_sql("show_buttons", False) == 0

    def test_json_serialization(self):
        from reverse_image_search_bot.config.db import _to_sql

        result = _to_sql("auto_search_engines", ["A", "B"])
        assert result == '["A", "B"]'

    def test_none_passthrough(self):
        from reverse_image_search_bot.config.db import _to_sql

        assert _to_sql("button_engines", None) is None


class TestSaveAndLoad:
    def test_save_and_load_config(self):
        from reverse_image_search_bot.config.db import load_config, save_config

        save_config(12345, {"show_buttons": True, "auto_search_enabled": False, "failures_in_a_row": 3})
        loaded = load_config(12345)
        assert loaded is not None
        assert loaded["show_buttons"] is True
        assert loaded["auto_search_enabled"] is False
        assert loaded["failures_in_a_row"] == 3

    def test_load_missing_returns_none(self):
        from reverse_image_search_bot.config.db import load_config

        assert load_config(99999) is None

    def test_save_field(self):
        from reverse_image_search_bot.config.db import load_config, save_config, save_field

        save_config(100, {"show_buttons": True})
        save_field(100, "show_buttons", False)
        loaded = load_config(100)
        assert loaded["show_buttons"] is False

    def test_save_field_creates_row(self):
        from reverse_image_search_bot.config.db import load_config, save_field

        save_field(200, "failures_in_a_row", 7)
        loaded = load_config(200)
        assert loaded is not None
        assert loaded["failures_in_a_row"] == 7

    def test_save_field_invalid_column(self):
        from reverse_image_search_bot.config.db import save_field

        with pytest.raises(ValueError, match="Unknown config column"):
            save_field(300, "nonexistent_column", "value")

    def test_json_field_roundtrip(self):
        from reverse_image_search_bot.config.db import load_config, save_config

        engines = ["SauceNAO", "Google", "Yandex"]
        save_config(400, {"auto_search_engines": engines})
        loaded = load_config(400)
        assert loaded["auto_search_engines"] == engines

    def test_engine_empty_counts_roundtrip(self):
        from reverse_image_search_bot.config.db import load_config, save_config

        counts = {"SauceNAO": 3, "Yandex": 1}
        save_config(500, {"engine_empty_counts": counts})
        loaded = load_config(500)
        assert loaded["engine_empty_counts"] == counts
