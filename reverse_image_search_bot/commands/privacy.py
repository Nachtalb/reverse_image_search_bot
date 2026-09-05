"""User-facing data commands: /privacy, /takeout, /delete.

/takeout and /delete act on the requester in a private chat and on the chat
itself in a group (admins only). Both are confirmation-gated through one
inline button; the same wording is used whatever the DB holds, so a reply
never reveals whether any material was retained.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import tempfile
import time
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from reverse_image_search_bot import metrics, privacy
from reverse_image_search_bot.i18n import lang as get_lang
from reverse_image_search_bot.i18n import t

from .settings import _is_settings_allowed

logger = logging.getLogger(__name__)

_PRIVACY_TEXT = (Path(__file__).parent.parent / "texts" / "privacy.html").read_text(encoding="utf-8")

TAKEOUT_COOLDOWN = 24 * 3600


async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    metrics.commands_total.labels(command="privacy").inc()
    await message.reply_text(_PRIVACY_TEXT, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def _subject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """Whose data a command acts on: the user in a DM, the chat in a group (admins only)."""
    chat, user = update.effective_chat, update.effective_user
    if not chat or not user or not update.effective_message:
        return None
    if chat.type == "private":
        return user.id
    if not await _is_settings_allowed(update, context):
        await update.effective_message.reply_text(t("privacy.admins_only", get_lang(update)))
        return None
    return chat.id


def _confirm_keyboard(action: str, user_id: int, L: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t(f"privacy.{action}_btn", L), callback_data=f"{action}:go:{user_id}"),
                InlineKeyboardButton(t("privacy.cancel_btn", L), callback_data=f"{action}:no:{user_id}"),
            ]
        ]
    )


async def takeout_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    metrics.commands_total.labels(command="takeout").inc()
    subject = await _subject(update, context)
    if subject is None:
        return
    assert update.effective_message and update.effective_user
    L = get_lang(update)
    store = context.chat_data if subject < 0 else context.user_data
    last = (store or {}).get("takeout_at", 0)
    if time.time() - last < TAKEOUT_COOLDOWN:
        hours = max(1, int((time.time() - last) // 3600))
        await update.effective_message.reply_text(t("privacy.takeout_cooldown", L, hours=hours))
        return
    key = "takeout_confirm_chat" if subject < 0 else "takeout_confirm"
    await update.effective_message.reply_text(
        t(f"privacy.{key}", L), reply_markup=_confirm_keyboard("takeout", update.effective_user.id, L)
    )


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    metrics.commands_total.labels(command="delete").inc()
    subject = await _subject(update, context)
    if subject is None:
        return
    assert update.effective_message and update.effective_user
    L = get_lang(update)
    key = "delete_confirm_chat" if subject < 0 else "delete_confirm"
    await update.effective_message.reply_text(
        t(f"privacy.{key}", L), reply_markup=_confirm_keyboard("delete", update.effective_user.id, L)
    )


async def privacy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ``takeout:*`` / ``delete:*`` confirmation buttons."""
    query = update.callback_query
    if not query or not query.data or not update.effective_chat or not update.effective_user:
        return
    action, choice, owner = query.data.split(":")
    L = get_lang(update)
    if update.effective_user.id != int(owner):
        await query.answer(t("privacy.not_yours", L), show_alert=True)
        return
    await query.answer()
    if choice != "go":
        await query.edit_message_text(t("privacy.cancelled", L))
        return
    chat = update.effective_chat
    subject = update.effective_user.id if chat.type == "private" else chat.id
    if action == "takeout":
        await _run_takeout(update, context, subject, L)
    else:
        await _run_delete(update, context, subject, L)


async def _run_takeout(update: Update, context: ContextTypes.DEFAULT_TYPE, subject: int, L: str) -> None:
    query = update.callback_query
    assert query and update.effective_chat
    await query.edit_message_text(t("privacy.takeout_wait", L))
    workdir = Path(tempfile.mkdtemp(prefix="takeout-"))
    try:
        parts = await asyncio.to_thread(privacy.build_takeout, subject, workdir)
        for i, part in enumerate(parts):
            with part.open("rb") as fh:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=fh,
                    filename=part.name,
                    caption=t("privacy.takeout_done", L) if i == 0 else None,
                )
        with contextlib.suppress(Exception):
            await query.delete_message()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    store = context.chat_data if subject < 0 else context.user_data
    if store is not None:
        store["takeout_at"] = time.time()
    logger.info("takeout subject=%s parts=%d", subject, len(parts))


async def _run_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, subject: int, L: str) -> None:
    query = update.callback_query
    assert query
    await asyncio.to_thread(privacy.erase, subject)
    store = context.chat_data if subject < 0 else context.user_data
    if store is not None:
        store.clear()
    await query.edit_message_text(t("privacy.delete_done", L))
    logger.info("erase subject=%s", subject)
