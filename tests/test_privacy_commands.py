"""Tests for the /takeout and /delete command flow (confirmation, admin gating, cooldown)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from reverse_image_search_bot.commands import privacy as pc


def _update(chat_type="private", chat_id=1, user_id=1, data=None):
    u = MagicMock()
    u.effective_chat.type = chat_type
    u.effective_chat.id = chat_id
    u.effective_user.id = user_id
    u.effective_message.reply_text = AsyncMock()
    u.callback_query = None
    if data:
        u.callback_query = MagicMock(data=data, answer=AsyncMock(), edit_message_text=AsyncMock())
    return u


def _ctx():
    c = MagicMock()
    c.user_data = {}
    c.chat_data = {}
    c.bot.send_document = AsyncMock()
    return c


@pytest.fixture(autouse=True)
def _lang(monkeypatch):
    monkeypatch.setattr(pc, "get_lang", lambda u: "en")


@pytest.mark.asyncio
async def test_takeout_dm_asks_for_confirmation():
    u = _update()
    await pc.takeout_command(u, _ctx())
    kb = u.effective_message.reply_text.call_args.kwargs["reply_markup"]
    assert [b.callback_data for b in kb.inline_keyboard[0]] == ["takeout:go:1", "takeout:no:1"]


@pytest.mark.asyncio
async def test_group_non_admin_is_refused(monkeypatch):
    monkeypatch.setattr(pc, "_is_settings_allowed", AsyncMock(return_value=False))
    u = _update("supergroup", -100, 5)
    await pc.delete_command(u, _ctx())
    assert "admins" in u.effective_message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_group_admin_gets_chat_confirmation(monkeypatch):
    monkeypatch.setattr(pc, "_is_settings_allowed", AsyncMock(return_value=True))
    u = _update("supergroup", -100, 5)
    await pc.delete_command(u, _ctx())
    assert "this chat" in u.effective_message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_takeout_cooldown():
    ctx = _ctx()
    ctx.user_data["takeout_at"] = time.time() - 3600
    u = _update()
    await pc.takeout_command(u, ctx)
    assert "try again" in u.effective_message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_callback_from_other_user_is_rejected(monkeypatch):
    erase = MagicMock()
    monkeypatch.setattr(pc.privacy, "erase", erase)
    u = _update(user_id=2, data="delete:go:1")
    await pc.privacy_callback(u, _ctx())
    u.callback_query.answer.assert_awaited_once()
    assert u.callback_query.answer.call_args.kwargs["show_alert"] is True
    erase.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_button(monkeypatch):
    erase = MagicMock()
    monkeypatch.setattr(pc.privacy, "erase", erase)
    u = _update(data="delete:no:1")
    await pc.privacy_callback(u, _ctx())
    erase.assert_not_called()
    assert u.callback_query.edit_message_text.call_args.args[0] == "Cancelled."


@pytest.mark.asyncio
async def test_delete_confirmed_erases_subject_and_clears_state(monkeypatch):
    erase = MagicMock()
    monkeypatch.setattr(pc.privacy, "erase", erase)
    ctx = _ctx()
    ctx.user_data["takeout_at"] = 1
    u = _update(data="delete:go:1")
    await pc.privacy_callback(u, ctx)
    erase.assert_called_once_with(1)
    assert ctx.user_data == {}
    assert "Done" in u.callback_query.edit_message_text.call_args.args[0]


@pytest.mark.asyncio
async def test_delete_in_group_targets_chat(monkeypatch):
    erase = MagicMock()
    monkeypatch.setattr(pc.privacy, "erase", erase)
    u = _update("supergroup", -100, 5, data="delete:go:5")
    await pc.privacy_callback(u, _ctx())
    erase.assert_called_once_with(-100)


@pytest.mark.asyncio
async def test_takeout_confirmed_sends_parts_and_cleans_up(monkeypatch, tmp_path):
    def fake_build(subject, workdir):
        parts = [workdir / "takeout-1-x.zip.001", workdir / "takeout-1-x.zip.002"]
        for p in parts:
            p.write_bytes(b"z")
        return parts

    monkeypatch.setattr(pc.privacy, "build_takeout", fake_build)
    made = []
    real_mkdtemp = pc.tempfile.mkdtemp
    monkeypatch.setattr(pc.tempfile, "mkdtemp", lambda **kw: made.append(real_mkdtemp(dir=tmp_path)) or made[-1])
    ctx = _ctx()
    u = _update(data="takeout:go:1")
    await pc.privacy_callback(u, ctx)
    calls = ctx.bot.send_document.await_args_list
    assert [c.kwargs["filename"] for c in calls] == ["takeout-1-x.zip.001", "takeout-1-x.zip.002"]
    assert calls[0].kwargs["caption"] and calls[1].kwargs["caption"] is None
    assert not pc.Path(made[0]).exists()
    assert "takeout_at" in ctx.user_data
