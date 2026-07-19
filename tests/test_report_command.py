"""Tests for the merged /report — single target OR pasted Cloudflare URLs."""

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


def _mk_update(text: str, chat_type: str = "group"):
    """Minimal Update stub: message with text + reply capture, user, chat."""
    replies: list[str] = []

    async def reply_html(t, **kw):
        replies.append(t)

    async def reply_text(t, **kw):
        replies.append(t)

    message = SimpleNamespace(text=text, reply_html=reply_html, reply_text=reply_text)
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(type=chat_type),
    )
    return update, replies


@pytest.mark.asyncio
async def test_report_bulk_urls_group_unique_users(abuse, tmp_path, monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.commands import report as rc

    updir = tmp_path / "uploads"
    updir.mkdir()
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}})
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")

    # User 1 has two listed files → ONE report. User 2 has one. Plus an unknown file.
    for uid, fname in [(1, "AAA.jpg"), (1, "BBB.jpg"), (2, "CCC.jpg")]:
        abuse.record_user(uid, username=f"u{uid}")
        abuse.record_file(fname.split(".")[0], saved_filename=fname, user_id=uid, file_type="photo")
        (updir / fname).write_bytes(b"data-" + fname.encode())

    text = (
        "/report URLs: hxxps://ris.naa[.]gg/f/AAA.jpg, hxxps://ris.naa[.]gg/f/BBB.jpg, "
        "hxxps://ris.naa[.]gg/f/CCC.jpg, hxxps://ris.naa[.]gg/f/UNKNOWN.jpg"
    )
    update, replies = _mk_update(text)
    context = SimpleNamespace(bot=AsyncMock())
    await rc.report_command(cast(Any, update), cast(Any, context))

    out = "\n".join(replies)
    # Two unique uploaders → two 🆕 rows (user 1 grouped despite two files).
    assert out.count("🆕") >= 2
    # Both users' P1 keys are surfaced as "P1 <code>…".
    assert out.count("P1 <code>") == 2
    # The unknown file is reported.
    assert "UNKNOWN.jpg" in out and "no uploader on record" in out
    # Reports actually exist, one active per user.
    assert abuse.active_report_for_user(1) is not None
    assert abuse.active_report_for_user(2) is not None


@pytest.mark.asyncio
async def test_report_single_target_by_username(abuse, tmp_path, monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.commands import report as rc

    updir = tmp_path / "uploads"
    updir.mkdir()
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}})
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")

    abuse.record_user(55, username="BadGuy")
    abuse.record_file("A", saved_filename="A.jpg", user_id=55, file_type="photo")
    (updir / "A.jpg").write_bytes(b"img")

    update, replies = _mk_update("/report @badguy")  # case-insensitive
    context = SimpleNamespace(bot=AsyncMock())
    await rc.report_command(cast(Any, update), cast(Any, context))

    out = "\n".join(replies)
    assert "🆕" in out and "55" in out and "P1 <code>" in out
    assert abuse.active_report_for_user(55) is not None


@pytest.mark.asyncio
async def test_report_already_filed_shows_ncmec_id(abuse, tmp_path, monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.commands import report as rc

    updir = tmp_path / "uploads"
    updir.mkdir()  # empty — nothing on disk
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}})
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")

    abuse.record_user(77, username="gone")
    abuse.record_file("D", saved_filename="D.jpg", user_id=77, file_type="photo")  # recorded, not on disk
    abuse.create_report("old", 77, "")
    abuse.add_report_blob(
        "old", file_unique_id="D", saved_filename="D.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    abuse.set_report_ncmec_id("old", 250926634)
    abuse.mark_report_filed("old")

    update, replies = _mk_update("/report 77")
    context = SimpleNamespace(bot=AsyncMock())
    await rc.report_command(cast(Any, update), cast(Any, context))

    out = "\n".join(replies)
    # Clean icon row, NOT the old wall of prose.
    assert "✅" in out and "filed NCMEC #250926634" in out
    assert "The plaintext files were deleted from disk" not in out


@pytest.mark.asyncio
async def test_report_usage_when_empty(abuse, monkeypatch):
    from reverse_image_search_bot.commands import report as rc

    update, replies = _mk_update("/report")
    context = SimpleNamespace(bot=AsyncMock())
    await rc.report_command(cast(Any, update), cast(Any, context))
    assert replies and "Usage:" in replies[0]


@pytest.mark.asyncio
async def test_report_unknown_target(abuse, monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.commands import report as rc

    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")
    update, replies = _mk_update("/report @nobody")
    context = SimpleNamespace(bot=AsyncMock())
    await rc.report_command(cast(Any, update), cast(Any, context))
    assert replies and "No uploader found" in replies[0]
