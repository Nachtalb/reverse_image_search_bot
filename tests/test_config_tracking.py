"""Tests for the insert-only abuse-tracking DB."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def tracking(tmp_path, monkeypatch):
    """Fresh tracking module bound to an isolated DB file per test."""
    import reverse_image_search_bot.settings as settings

    db_path = tmp_path / "tracking.db"
    monkeypatch.setattr(settings, "TRACKING_DB_PATH", db_path)

    import reverse_image_search_bot.config.tracking as tr

    # Reset thread-local connections so the new path takes effect.
    tr._local.__dict__.clear()
    tr._all_connections.clear()
    importlib.reload(tr)
    monkeypatch.setattr(tr, "TRACKING_DB_PATH", db_path)
    tr._local.__dict__.clear()
    tr._all_connections.clear()
    return tr


def test_record_user_upserts_last_seen_wins(tracking):
    tracking.record_user(1, username="alice", first_name="Alice")
    tracking.record_user(1, username="alice2", first_name="Alice", last_name="B")
    user = tracking.get_user(1)
    assert user["username"] == "alice2"
    assert user["last_name"] == "B"
    assert user["banned_at"] is None


def test_record_file_is_insert_only(tracking):
    tracking.record_user(1, username="alice")
    tracking.record_file("FID1", saved_filename="FID1.jpg", user_id=1, file_type="photo")
    # Second call with a different saved_filename must NOT overwrite the row.
    tracking.record_file("FID1", saved_filename="OTHER.jpg", user_id=99)
    files = tracking.files_for_user(1)
    assert len(files) == 1
    assert files[0]["saved_filename"] == "FID1.jpg"
    assert files[0]["user_id"] == 1
    assert tracking.count_files(1) == 1
    assert tracking.count_files(99) == 0


def test_ban_toggle_and_sync(tracking):
    tracking.record_user(1, username="alice")
    assert tracking.is_banned(1) is False
    tracking.set_banned(1, True)
    assert tracking.is_banned(1) is True
    assert tracking.banned_user_ids() == [1]
    tracking.set_banned(1, False)
    assert tracking.is_banned(1) is False
    assert tracking.banned_user_ids() == []


def test_set_banned_creates_bare_user(tracking):
    # Banning a user we've never seen still records them (for startup sync).
    tracking.set_banned(555, True)
    assert tracking.is_banned(555) is True
    assert 555 in tracking.banned_user_ids()


def test_find_user_by_filename(tracking):
    tracking.record_user(7, username="bob")
    tracking.record_file("AQADxyz", saved_filename="AQADxyz.jpg", user_id=7)
    assert tracking.find_user_by_filename("AQADxyz.jpg") == 7  # full filename (Cloudflare form)
    assert tracking.find_user_by_filename("AQADxyz") == 7  # bare file_unique_id
    assert tracking.find_user_by_filename("nonexistent.jpg") is None


def test_has_report_false_without_reports_table(tracking):
    # Phase 1: no reports table exists yet — must degrade to False, not raise.
    tracking.record_user(1, username="alice")
    assert tracking.has_report(1) is False


def test_count_files_multiple(tracking):
    tracking.record_user(1)
    for i in range(3):
        tracking.record_file(f"F{i}", saved_filename=f"F{i}.jpg", user_id=1)
    assert tracking.count_files(1) == 3
