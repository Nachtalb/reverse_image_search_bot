"""Reporting a group/channel target reports its uploaders, not the chat id."""

from __future__ import annotations

import importlib
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

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


def _update():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.reply_html = AsyncMock()
    update.effective_chat.type = "private"
    return update


def _context():
    ctx = MagicMock()
    ctx.bot.set_chat_menu_button = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_chat_target_expands_to_its_uploaders(abuse, monkeypatch):
    """A negative id is a chat: report everyone who uploaded through it."""
    from reverse_image_search_bot.commands import report as rc

    prepared = []
    monkeypatch.setattr(rc.abuse, "uploaders_for_chat", lambda cid: [10, 20] if cid == -100123 else [])

    def fake_prepare(uid, progress=None, indicators=None):
        prepared.append(uid)
        return MagicMock(ok=False, existing_uuid=None, filed_ncmec_id=None)

    monkeypatch.setattr(rc, "prepare_report", fake_prepare)

    update = _update()
    await rc.report_users(cast(Any, update), cast(Any, _context()), [-100123])
    # The chat id itself is NEVER handed to prepare_report — it is not a user.
    assert prepared == [10, 20]


@pytest.mark.asyncio
async def test_chat_and_user_targets_mix_and_dedupe(abuse, monkeypatch):
    from reverse_image_search_bot.commands import report as rc

    prepared = []
    monkeypatch.setattr(rc.abuse, "uploaders_for_chat", lambda cid: [10, 999])

    def fake_prepare(uid, progress=None, indicators=None):
        prepared.append(uid)
        return MagicMock(ok=False, existing_uuid=None, filed_ncmec_id=None)

    monkeypatch.setattr(rc, "prepare_report", fake_prepare)

    update = _update()
    # 999 arrives both directly and via the chat — it must be reported once.
    await rc.report_users(cast(Any, update), cast(Any, _context()), [999, -100123])
    assert prepared == [999, 10]


@pytest.mark.asyncio
async def test_chat_with_no_uploaders_says_so_and_prepares_nothing(abuse, monkeypatch):
    from reverse_image_search_bot.commands import report as rc

    prepared = []
    monkeypatch.setattr(rc.abuse, "uploaders_for_chat", lambda cid: [])
    monkeypatch.setattr(rc, "prepare_report", lambda *a, **k: prepared.append(a) or MagicMock(ok=False))

    update = _update()
    await rc.report_users(cast(Any, update), cast(Any, _context()), [-100123])
    assert prepared == []
    assert "No uploaders recorded" in update.message.reply_html.call_args[0][0]
