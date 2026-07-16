"""Tests for the insert-only abuse-report DB."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def abuse(tmp_path, monkeypatch):
    """Fresh abuse module bound to an isolated DB file per test."""
    import reverse_image_search_bot.settings as settings

    db_path = tmp_path / "abuse.db"
    monkeypatch.setattr(settings, "ABUSE_DB_PATH", db_path)

    import reverse_image_search_bot.config.abuse as ab

    # Reset thread-local connections so the new path takes effect.
    ab._local.__dict__.clear()
    ab._all_connections.clear()
    importlib.reload(ab)
    monkeypatch.setattr(ab, "ABUSE_DB_PATH", db_path)
    ab._local.__dict__.clear()
    ab._all_connections.clear()
    return ab


def test_record_user_upserts_last_seen_wins(abuse):
    abuse.record_user(1, username="alice", first_name="Alice")
    abuse.record_user(1, username="alice2", first_name="Alice", last_name="B")
    user = abuse.get_user(1)
    assert user["username"] == "alice2"
    assert user["last_name"] == "B"
    assert user["banned_at"] is None


def test_record_file_is_insert_only(abuse):
    abuse.record_user(1, username="alice")
    abuse.record_file("FID1", saved_filename="FID1.jpg", user_id=1, file_type="photo")
    # Second call with a different saved_filename must NOT overwrite the row.
    abuse.record_file("FID1", saved_filename="OTHER.jpg", user_id=99)
    files = abuse.files_for_user(1)
    assert len(files) == 1
    assert files[0]["saved_filename"] == "FID1.jpg"
    assert files[0]["user_id"] == 1
    assert abuse.count_files(1) == 1
    assert abuse.count_files(99) == 0


def test_ban_toggle_and_sync(abuse):
    abuse.record_user(1, username="alice")
    assert abuse.is_banned(1) is False
    abuse.set_banned(1, True)
    assert abuse.is_banned(1) is True
    assert abuse.banned_user_ids() == [1]
    abuse.set_banned(1, False)
    assert abuse.is_banned(1) is False
    assert abuse.banned_user_ids() == []


def test_set_banned_creates_bare_user(abuse):
    # Banning a user we've never seen still records them (for startup sync).
    abuse.set_banned(555, True)
    assert abuse.is_banned(555) is True
    assert 555 in abuse.banned_user_ids()


def test_find_user_by_filename(abuse):
    abuse.record_user(7, username="bob")
    abuse.record_file("AQADxyz", saved_filename="AQADxyz.jpg", user_id=7)
    assert abuse.find_user_by_filename("AQADxyz.jpg") == 7  # full filename (Cloudflare form)
    assert abuse.find_user_by_filename("AQADxyz") == 7  # bare file_unique_id
    assert abuse.find_user_by_filename("nonexistent.jpg") is None


def test_has_report_false_without_reports_table(abuse):
    # Phase 1: no reports table exists yet — must degrade to False, not raise.
    abuse.record_user(1, username="alice")
    assert abuse.has_report(1) is False


def test_count_files_multiple(abuse):
    abuse.record_user(1)
    for i in range(3):
        abuse.record_file(f"F{i}", saved_filename=f"F{i}.jpg", user_id=1)
    assert abuse.count_files(1) == 3
