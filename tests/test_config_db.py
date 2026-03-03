"""Tests for reverse_image_search_bot.config.db — uses temp SQLite."""

import contextlib
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path):  # tmp_path is a built-in pytest fixture (unique temp dir per test)
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

    def test_non_special_none_returns_none(self):
        from reverse_image_search_bot.config.db import _to_python

        assert _to_python("failures_in_a_row", None) is None


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


class TestToSqlDefault:
    def test_bool_default(self):
        from reverse_image_search_bot.config.db import _to_sql_default

        assert _to_sql_default(True) == "1"
        assert _to_sql_default(False) == "0"

    def test_int_default(self):
        from reverse_image_search_bot.config.db import _to_sql_default

        assert _to_sql_default(42) == "42"

    def test_str_default(self):
        from reverse_image_search_bot.config.db import _to_sql_default

        assert _to_sql_default("hello") == "'hello'"

    def test_none_default(self):
        from reverse_image_search_bot.config.db import _to_sql_default

        assert _to_sql_default(None) == "NULL"

    def test_unknown_type_default(self):
        from reverse_image_search_bot.config.db import _to_sql_default

        assert _to_sql_default([1, 2, 3]) == "NULL"
        assert _to_sql_default(3.14) == "NULL"


class TestCloseAllConnections:
    def test_close_all(self):
        """_close_all_connections should close all tracked connections."""
        import reverse_image_search_bot.config.db as db_mod

        # Force a connection so _all_connections is non-empty
        db_mod._get_conn()
        assert len(db_mod._all_connections) > 0
        db_mod._close_all_connections()
        assert len(db_mod._all_connections) == 0


class TestMigrateJsonFiles:
    def test_migrate_full_chat_config(self, tmp_path, _fresh_db):
        """A full old chat config JSON should be completely imported with no data missed."""
        import json

        from reverse_image_search_bot.config.db import load_config, migrate_json_files

        config_dir = tmp_path / "configs"
        config_dir.mkdir()

        full_config = {
            "show_buttons": False,
            "show_best_match": True,
            "show_link": False,
            "auto_search_enabled": True,
            "auto_search_engines": ["SauceNAO", "Yandex"],
            "button_engines": ["Google", "Bing"],
            "engine_empty_counts": {"SauceNAO": 2, "Trace": 4},
            "onboarded": True,
            "failures_in_a_row": 3,
        }
        chat_file = config_dir / "55555_chat.json"
        chat_file.write_text(json.dumps(full_config))

        count = migrate_json_files(config_dir)
        assert count == 1

        loaded = load_config(55555)
        assert loaded is not None
        assert loaded["show_buttons"] is False
        assert loaded["show_best_match"] is True
        assert loaded["show_link"] is False
        assert loaded["auto_search_enabled"] is True
        assert loaded["auto_search_engines"] == ["SauceNAO", "Yandex"]
        assert loaded["button_engines"] == ["Google", "Bing"]
        assert loaded["engine_empty_counts"] == {"SauceNAO": 2, "Trace": 4}
        assert loaded["onboarded"] is True
        assert loaded["failures_in_a_row"] == 3

    def test_migrate_chat_config(self, tmp_path, _fresh_db):
        import json

        from reverse_image_search_bot.config.db import load_config, migrate_json_files

        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        chat_file = config_dir / "12345_chat.json"
        chat_file.write_text(json.dumps({"show_buttons": False, "auto_search_enabled": True}))

        count = migrate_json_files(config_dir)
        assert count == 1
        loaded = load_config(12345)
        assert loaded is not None
        assert loaded["show_buttons"] is False
        # Original file should be renamed to .bak
        assert not chat_file.exists()
        assert chat_file.with_suffix(".json.bak").exists()

    def test_migrate_user_config_with_disabled_auto_search(self, tmp_path, _fresh_db):
        import json

        from reverse_image_search_bot.config.db import load_config, migrate_json_files

        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        user_file = config_dir / "99999.json"
        user_file.write_text(json.dumps({"auto_search_enabled": False}))

        count = migrate_json_files(config_dir)
        assert count == 1
        loaded = load_config(99999)
        assert loaded is not None
        assert loaded["auto_search_enabled"] is False

    def test_migrate_skips_already_loaded(self, tmp_path, _fresh_db):
        import json

        from reverse_image_search_bot.config.db import migrate_json_files, save_config

        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        chat_file = config_dir / "12345_chat.json"
        chat_file.write_text(json.dumps({"show_buttons": True}))

        # Pre-save so migration skips
        save_config(12345, {"show_buttons": False})
        count = migrate_json_files(config_dir)
        assert count == 0

    def test_migrate_skips_invalid_json(self, tmp_path, _fresh_db):
        from reverse_image_search_bot.config.db import migrate_json_files

        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        bad_file = config_dir / "bad_chat.json"
        bad_file.write_text("not json at all {{{")

        count = migrate_json_files(config_dir)
        assert count == 0

    def test_migrate_user_with_auto_search_enabled_skipped(self, tmp_path, _fresh_db):
        """User configs with auto_search_enabled=True should not create DB entries."""
        import json

        from reverse_image_search_bot.config.db import load_config, migrate_json_files

        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        user_file = config_dir / "77777.json"
        user_file.write_text(json.dumps({"auto_search_enabled": True}))

        count = migrate_json_files(config_dir)
        assert count == 0
        assert load_config(77777) is None

    def test_migrate_empty_directory(self, tmp_path, _fresh_db):
        from reverse_image_search_bot.config.db import migrate_json_files

        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        assert migrate_json_files(config_dir) == 0

    def test_migrate_user_invalid_filename_skipped(self, tmp_path, _fresh_db):
        """User JSON files with non-integer stems should be skipped."""
        import json

        from reverse_image_search_bot.config.db import migrate_json_files

        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        bad_user = config_dir / "notanumber.json"
        bad_user.write_text(json.dumps({"auto_search_enabled": False}))

        count = migrate_json_files(config_dir)
        assert count == 0


class TestEnsureSchema:
    def test_non_duplicate_column_error_reraises(self, tmp_path):
        """ALTER TABLE errors other than 'duplicate column' should be re-raised."""
        import sqlite3

        import reverse_image_search_bot.config.db as db_mod

        # Use a fresh connection to a new DB
        db_path = tmp_path / "schema_err.db"
        real_conn = sqlite3.connect(str(db_path))
        real_conn.execute("CREATE TABLE IF NOT EXISTS chat_config (chat_id INTEGER PRIMARY KEY)")
        real_conn.commit()

        # Wrap with MagicMock to intercept execute
        from unittest.mock import MagicMock

        conn = MagicMock(wraps=real_conn)
        call_count = 0

        def patched_execute(sql, *args, **kwargs):
            nonlocal call_count
            # Let CREATE TABLE through, fail on ALTER TABLE
            if "ALTER TABLE" in sql:
                raise sqlite3.OperationalError("disk I/O error")
            return real_conn.execute(sql, *args, **kwargs)

        conn.execute = patched_execute

        with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
            db_mod._ensure_schema(conn)

        real_conn.close()
