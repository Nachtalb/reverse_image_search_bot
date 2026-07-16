"""Tests for the admin /ban and /check commands (bot.py) — dual-write + lookup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from reverse_image_search_bot.bot import ban_command, check_command


def _update(text: str):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.reply_html = AsyncMock()
    return update


def _context(banned=None):
    ctx = MagicMock()
    ctx.bot_data = {"banned_users": list(banned or [])}
    return ctx


@pytest.mark.asyncio
async def test_ban_writes_both_memory_and_db(monkeypatch):
    calls = []
    monkeypatch.setattr("reverse_image_search_bot.bot.abuse.set_banned", lambda uid, b: calls.append((uid, b)))
    monkeypatch.setattr("reverse_image_search_bot.bot.abuse.has_report", lambda uid: False)
    update = _update("/ban 12345")
    ctx = _context()
    await ban_command(update, ctx)
    assert 12345 in ctx.bot_data["banned_users"]  # memory
    assert calls == [(12345, True)]  # DB


@pytest.mark.asyncio
async def test_unban_toggles_both(monkeypatch):
    calls = []
    monkeypatch.setattr("reverse_image_search_bot.bot.abuse.set_banned", lambda uid, b: calls.append((uid, b)))
    monkeypatch.setattr("reverse_image_search_bot.bot.abuse.has_report", lambda uid: False)
    update = _update("/ban 12345")
    ctx = _context(banned=[12345])
    await ban_command(update, ctx)
    assert 12345 not in ctx.bot_data["banned_users"]
    assert calls == [(12345, False)]


@pytest.mark.asyncio
async def test_ban_no_arg_lists_with_report_flag(monkeypatch):
    monkeypatch.setattr("reverse_image_search_bot.bot.abuse.has_report", lambda uid: uid == 111)
    update = _update("/ban")
    ctx = _context(banned=[111, 222])
    await ban_command(update, ctx)
    sent = update.message.reply_html.call_args[0][0]
    assert "111" in sent and "🚩" in sent
    assert "222" in sent


@pytest.mark.asyncio
async def test_ban_no_arg_empty(monkeypatch):
    update = _update("/ban")
    ctx = _context(banned=[])
    await ban_command(update, ctx)
    update.message.reply_text.assert_awaited_once()
    assert "No users" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_check_by_user_id(monkeypatch):
    monkeypatch.setattr("reverse_image_search_bot.bot.abuse.count_files", lambda uid: 4)
    monkeypatch.setattr("reverse_image_search_bot.bot.abuse.get_user", lambda uid: {"username": "bob"})
    monkeypatch.setattr("reverse_image_search_bot.bot.abuse.has_report", lambda uid: False)
    update = _update("/check 777")
    ctx = _context()
    await check_command(update, ctx)
    sent = update.message.reply_html.call_args[0][0]
    assert "777" in sent and "4" in sent and "bob" in sent


@pytest.mark.asyncio
async def test_check_by_filename_resolves_user(monkeypatch):
    monkeypatch.setattr("reverse_image_search_bot.bot.abuse.find_user_by_filename", lambda f: 888)
    monkeypatch.setattr("reverse_image_search_bot.bot.abuse.count_files", lambda uid: 2)
    monkeypatch.setattr("reverse_image_search_bot.bot.abuse.get_user", lambda uid: None)
    monkeypatch.setattr("reverse_image_search_bot.bot.abuse.has_report", lambda uid: False)
    update = _update("/check AQADxyz.jpg")
    ctx = _context()
    await check_command(update, ctx)
    sent = update.message.reply_html.call_args[0][0]
    assert "888" in sent and "AQADxyz.jpg" in sent


@pytest.mark.asyncio
async def test_check_filename_not_found(monkeypatch):
    monkeypatch.setattr("reverse_image_search_bot.bot.abuse.find_user_by_filename", lambda f: None)
    update = _update("/check missing.jpg")
    ctx = _context()
    await check_command(update, ctx)
    update.message.reply_text.assert_awaited_once()
    assert "No uploader" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_check_no_arg_usage():
    update = _update("/check")
    ctx = _context()
    await check_command(update, ctx)
    update.message.reply_text.assert_awaited_once()
    assert "Usage" in update.message.reply_text.call_args[0][0]
