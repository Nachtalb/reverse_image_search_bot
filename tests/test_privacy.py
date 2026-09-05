"""Tests for the user-facing data handling module (retention, takeout, erase)."""

from __future__ import annotations

import os
import time

import pytest

from reverse_image_search_bot import privacy, settings


@pytest.fixture
def updir(tmp_path, monkeypatch):
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(settings, "UPLOADER", {"uploader": "local", "configuration": {"path": str(d)}})
    monkeypatch.setattr(settings, "FILE_RETENTION_DAYS", 30)
    return d


def _touch(path, age_days: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    mtime = time.time() - age_days * 86400
    os.utime(path, (mtime, mtime))


def test_sweep_removes_only_expired_top_level_files(updir):
    _touch(updir / "old.jpg", 40)
    _touch(updir / "new.jpg", 1)
    _touch(updir / "report_videos" / "old.enc", 40)
    _touch(updir / "held" / "1" / "x.enc", 40)
    _touch(updir / "report_files" / "u" / "x.enc", 40)

    assert privacy.sweep_expired_uploads() == 1

    assert not (updir / "old.jpg").exists()
    assert (updir / "new.jpg").exists()
    assert (updir / "report_videos" / "old.enc").exists()
    assert (updir / "held" / "1" / "x.enc").exists()
    assert (updir / "report_files" / "u" / "x.enc").exists()


def test_sweep_noop_without_upload_dir(monkeypatch):
    monkeypatch.setattr(settings, "UPLOADER", {"uploader": "ssh", "configuration": {}})
    assert privacy.sweep_expired_uploads() == 0


@pytest.mark.asyncio
async def test_retention_job_runs_sweep(monkeypatch):
    from unittest.mock import MagicMock

    from reverse_image_search_bot import bot

    sweep = MagicMock(return_value=3)
    monkeypatch.setattr(bot.privacy, "sweep_expired_uploads", sweep)
    await bot.retention_job(MagicMock())
    sweep.assert_called_once_with()
