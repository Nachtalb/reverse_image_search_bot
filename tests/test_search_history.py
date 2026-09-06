"""Search history: the `searches` table, its CRUD, and the one-shot backfill."""

from __future__ import annotations

import importlib
import sqlite3

import pytest


@pytest.fixture
def abuse(tmp_path, monkeypatch):
    import reverse_image_search_bot.settings as settings

    db_path = tmp_path / "abuse.db"
    monkeypatch.setattr(settings, "ABUSE_DB_PATH", db_path)
    import reverse_image_search_bot.config.abuse as ab

    ab._local.__dict__.clear()
    ab._all_connections.clear()
    importlib.reload(ab)
    monkeypatch.setattr(ab, "ABUSE_DB_PATH", db_path)
    ab._local.__dict__.clear()
    ab._all_connections.clear()
    return ab


class TestRecording:
    def test_record_and_read_back(self, abuse):
        abuse.record_user(7, username="nick")
        sid = abuse.record_search(7, chat_id=7, message_id=100, file_unique_id="F1")
        assert sid > 0
        history = abuse.user_searches(7)
        assert len(history) == 1
        assert history[0]["file_unique_id"] == "F1"
        assert history[0]["results"] == []

    def test_results_attach_to_an_open_entry(self, abuse):
        abuse.record_user(7)
        sid = abuse.record_search(7, file_unique_id="F1")
        abuse.set_search_results(sid, [{"engine": "SauceNAO", "title": "Found", "url": "https://e.com"}])
        entry = abuse.user_searches(7)[0]
        assert entry["results"][0]["engine"] == "SauceNAO"
        assert entry["results"][0]["title"] == "Found"

    def test_newest_first(self, abuse):
        abuse.record_user(7)
        first = abuse.record_search(7, file_unique_id="OLD")
        second = abuse.record_search(7, file_unique_id="NEW")
        ids = [e["search_id"] for e in abuse.user_searches(7)]
        assert ids == [second, first]

    def test_thumbnail_filename_comes_from_the_files_row(self, abuse):
        abuse.record_user(7)
        abuse.record_file("F1", saved_filename="F1.jpg", user_id=7, file_type="photo")
        abuse.record_search(7, file_unique_id="F1")
        assert abuse.user_searches(7)[0]["saved_filename"] == "F1.jpg"

    def test_entry_survives_a_swept_upload(self, abuse):
        """Retention removes the image, not the memory of having searched it."""
        abuse.record_user(7)
        abuse.record_search(7, file_unique_id="GONE")
        entry = abuse.user_searches(7)[0]
        assert entry["file_unique_id"] == "GONE"
        assert entry["saved_filename"] is None

    def test_undecodable_results_degrade_to_empty(self, abuse):
        abuse.record_user(7)
        sid = abuse.record_search(7, file_unique_id="F1")
        conn = abuse._get_conn()
        with conn:
            conn.execute("UPDATE searches SET results = 'not json' WHERE search_id = ?", (sid,))
        assert abuse.user_searches(7)[0]["results"] == []


class TestIsolation:
    def test_a_user_only_ever_sees_their_own(self, abuse):
        abuse.record_user(1)
        abuse.record_user(2)
        abuse.record_search(1, file_unique_id="MINE")
        abuse.record_search(2, file_unique_id="THEIRS")
        assert [e["file_unique_id"] for e in abuse.user_searches(1)] == ["MINE"]
        assert abuse.count_user_searches(1) == 1

    def test_get_is_scoped_to_the_owner(self, abuse):
        abuse.record_user(1)
        abuse.record_user(2)
        sid = abuse.record_search(1, file_unique_id="MINE")
        assert abuse.get_user_search(1, sid) is not None
        assert abuse.get_user_search(2, sid) is None

    def test_delete_is_scoped_to_the_owner(self, abuse):
        abuse.record_user(1)
        abuse.record_user(2)
        sid = abuse.record_search(1, file_unique_id="MINE")
        assert abuse.delete_user_search(2, sid) is False
        assert abuse.count_user_searches(1) == 1
        assert abuse.delete_user_search(1, sid) is True
        assert abuse.count_user_searches(1) == 0

    def test_deleting_history_keeps_the_provenance_row(self, abuse):
        """History is the user's; the abuse record is not theirs to erase."""
        abuse.record_user(1)
        abuse.record_file("F1", saved_filename="F1.jpg", user_id=1)
        sid = abuse.record_search(1, file_unique_id="F1")
        abuse.delete_user_search(1, sid)
        assert abuse.file_by_unique_id("F1") is not None

    def test_delete_all_for_user(self, abuse):
        abuse.record_user(1)
        abuse.record_user(2)
        abuse.record_search(1, file_unique_id="A")
        abuse.record_search(1, file_unique_id="B")
        abuse.record_search(2, file_unique_id="C")
        assert abuse.delete_searches_for_user(1) == 2
        assert abuse.count_user_searches(1) == 0
        assert abuse.count_user_searches(2) == 1


class TestPaging:
    def test_limit_and_offset(self, abuse):
        abuse.record_user(7)
        for i in range(5):
            abuse.record_search(7, file_unique_id=f"F{i}")
        page1 = abuse.user_searches(7, limit=2, offset=0)
        page2 = abuse.user_searches(7, limit=2, offset=2)
        assert len(page1) == len(page2) == 2
        assert {e["search_id"] for e in page1}.isdisjoint({e["search_id"] for e in page2})
        assert abuse.count_user_searches(7) == 5


class TestBackfill:
    """Existing users must not open the app to an empty list."""

    def _old_db(self, path, rows):
        """A DB with `files` but no `searches` — the pre-feature shape."""
        conn = sqlite3.connect(str(path))
        conn.execute(
            "CREATE TABLE users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, "
            "language_code TEXT, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL, banned_at INTEGER)"
        )
        conn.execute(
            "CREATE TABLE files (file_unique_id TEXT PRIMARY KEY, saved_filename TEXT NOT NULL, "
            "original_filename TEXT, file_type TEXT, upload_time INTEGER NOT NULL, user_id INTEGER NOT NULL, "
            "group_id INTEGER, channel_id INTEGER, hold_reason TEXT)"
        )
        conn.execute("INSERT INTO users VALUES (1, 'a', NULL, NULL, NULL, 100, 100, NULL)")
        for fid, gid, cid, hold in rows:
            conn.execute(
                "INSERT INTO files (file_unique_id, saved_filename, upload_time, user_id, group_id, channel_id, "
                "hold_reason) VALUES (?, ?, ?, 1, ?, ?, ?)",
                (fid, f"{fid}.jpg", 100, gid, cid, hold),
            )
        conn.commit()
        conn.close()

    def _open(self, path, monkeypatch):
        import reverse_image_search_bot.settings as settings

        monkeypatch.setattr(settings, "ABUSE_DB_PATH", path)
        import reverse_image_search_bot.config.abuse as ab

        ab._local.__dict__.clear()
        ab._all_connections.clear()
        importlib.reload(ab)
        monkeypatch.setattr(ab, "ABUSE_DB_PATH", path)
        ab._local.__dict__.clear()
        ab._all_connections.clear()
        return ab

    def test_private_uploads_become_history(self, tmp_path, monkeypatch):
        path = tmp_path / "old.db"
        self._old_db(path, [("A", None, None, None), ("B", None, None, None)])
        ab = self._open(path, monkeypatch)
        assert ab.count_user_searches(1) == 2
        assert {e["file_unique_id"] for e in ab.user_searches(1)} == {"A", "B"}

    def test_group_and_channel_uploads_are_excluded(self, tmp_path, monkeypatch):
        """History is personal: what was sent in a group is not the user's private record."""
        path = tmp_path / "old.db"
        self._old_db(path, [("PRIV", None, None, None), ("GRP", -100, None, None), ("CHAN", None, -200, None)])
        ab = self._open(path, monkeypatch)
        assert [e["file_unique_id"] for e in ab.user_searches(1)] == ["PRIV"]

    def test_held_uploads_are_excluded(self, tmp_path, monkeypatch):
        """A banned user's held evidence is not a search they get to browse."""
        path = tmp_path / "old.db"
        self._old_db(path, [("OK", None, None, None), ("HELD", None, None, "after_ban")])
        ab = self._open(path, monkeypatch)
        assert [e["file_unique_id"] for e in ab.user_searches(1)] == ["OK"]

    def test_backfilled_rows_carry_the_original_time_and_no_results(self, tmp_path, monkeypatch):
        path = tmp_path / "old.db"
        self._old_db(path, [("A", None, None, None)])
        ab = self._open(path, monkeypatch)
        entry = ab.user_searches(1)[0]
        assert entry["searched_at"] == 100
        assert entry["results"] == []

    def test_runs_once_and_does_not_duplicate(self, tmp_path, monkeypatch):
        path = tmp_path / "old.db"
        self._old_db(path, [("A", None, None, None)])
        ab = self._open(path, monkeypatch)
        assert ab.count_user_searches(1) == 1
        # Re-running the schema pass (every new thread does) must not re-seed.
        ab._ensure_schema(ab._get_conn())
        ab._ensure_schema(ab._get_conn())
        assert ab.count_user_searches(1) == 1

    def test_a_real_search_blocks_a_later_reseed(self, abuse):
        """Once there is genuine history, the backfill must never fire again."""
        abuse.record_user(1)
        abuse.record_file("OLD", saved_filename="OLD.jpg", user_id=1)
        abuse.record_search(1, file_unique_id="LIVE")
        abuse._ensure_schema(abuse._get_conn())
        assert [e["file_unique_id"] for e in abuse.user_searches(1)] == ["LIVE"]

    def test_a_fresh_db_starts_empty(self, abuse):
        assert abuse.count_user_searches(1) == 0
