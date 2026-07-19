"""Tests for /bulkreport — parse Cloudflare URLs, report per unique new uploader."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

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


def test_cf_file_regex_defanged_and_plain():
    from reverse_image_search_bot.commands.report import _CF_FILE_RE

    text = (
        "URLs: hxxps://ris.naa[.]gg/f/AQADsAxrG35d6EZ9.jpg, "
        "hxxps://ris.naa[.]gg/f/AgADkAcAAn5d6EY.jpg, "
        "https://ris.naa.gg/f/Zz_9-Ab.png"
    )
    assert _CF_FILE_RE.findall(text) == [
        "AQADsAxrG35d6EZ9.jpg",
        "AgADkAcAAn5d6EY.jpg",
        "Zz_9-Ab.png",
    ]


def test_cf_file_regex_ignores_non_f_paths():
    from reverse_image_search_bot.commands.report import _CF_FILE_RE

    # Only /f/<file> matches; other paths (e.g. /d/ debug, /report/) are ignored.
    text = "https://ris.naa.gg/d/skip.jpg https://ris.naa.gg/report/abc https://ris.naa.gg/f/keep.jpg"
    assert _CF_FILE_RE.findall(text) == ["keep.jpg"]


def _mk_update(text: str):
    """Minimal Update stub: message with text + reply capture, effective_user."""
    replies: list[str] = []

    async def reply_html(t, **kw):
        replies.append(t)

    async def reply_text(t, **kw):
        replies.append(t)

    message = SimpleNamespace(text=text, reply_html=reply_html, reply_text=reply_text)
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=42))
    return update, replies


@pytest.mark.asyncio
async def test_bulkreport_groups_unique_users_and_reports(abuse, tmp_path, monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.commands import report as rc

    updir = tmp_path / "uploads"
    updir.mkdir()
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}})
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")

    # Two users. User 1 has two files (both listed) → ONE report. User 2 has one.
    for uid, fname in [(1, "AAA.jpg"), (1, "BBB.jpg"), (2, "CCC.jpg")]:
        abuse.record_user(uid, username=f"u{uid}")
        abuse.record_file(fname.split(".")[0], saved_filename=fname, user_id=uid, file_type="photo")
        (updir / fname).write_bytes(b"data-" + fname.encode())

    text = (
        "URLs: hxxps://ris.naa[.]gg/f/AAA.jpg, hxxps://ris.naa[.]gg/f/BBB.jpg, "
        "hxxps://ris.naa[.]gg/f/CCC.jpg, hxxps://ris.naa[.]gg/f/UNKNOWN.jpg"
    )
    update, replies = _mk_update(text)
    context = SimpleNamespace(bot=AsyncMock())

    await rc.bulk_report_command(cast(Any, update), cast(Any, context))

    out = "\n".join(replies)
    # Two unique uploaders → two new reports (user 1 grouped despite two files).
    assert "2 uploader(s)" in out
    assert "<b>New reports:</b> 2" in out
    # Both users' P1 keys are surfaced.
    assert out.count("<b>P1:</b>") == 2
    # The unknown file is reported as such.
    assert "UNKNOWN.jpg" in out and "Unknown files:</b> 1" in out
    # Reports actually exist in the DB, one active per user.
    assert abuse.active_report_for_user(1) is not None
    assert abuse.active_report_for_user(2) is not None


@pytest.mark.asyncio
async def test_bulkreport_skips_already_filed(abuse, tmp_path, monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.commands import report as rc

    updir = tmp_path / "uploads"
    updir.mkdir()
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}})
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")

    # User 3's file is recorded but NOT on disk (already filed & deleted) → skipped.
    abuse.record_user(3, username="gone")
    abuse.record_file("DDD", saved_filename="DDD.jpg", user_id=3, file_type="photo")

    update, replies = _mk_update("URLs: https://ris.naa.gg/f/DDD.jpg")
    context = SimpleNamespace(bot=AsyncMock())
    await rc.bulk_report_command(cast(Any, update), cast(Any, context))

    out = "\n".join(replies)
    assert "<b>New reports:</b> 0" in out
    assert "<b>Skipped:</b> 1" in out
    assert abuse.active_report_for_user(3) is None


@pytest.mark.asyncio
async def test_bulkreport_no_urls(abuse, monkeypatch):
    from reverse_image_search_bot.commands import report as rc

    update, replies = _mk_update("/bulkreport just some text no urls")
    context = SimpleNamespace(bot=AsyncMock())
    await rc.bulk_report_command(cast(Any, update), cast(Any, context))
    assert replies and "No file URLs found" in replies[0]
