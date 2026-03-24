from __future__ import annotations

import contextlib
import json

from telegram import KeyboardButton, Message, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from reverse_image_search_bot import metrics
from reverse_image_search_bot.config import ChatConfig
from reverse_image_search_bot.i18n import lang as get_lang
from reverse_image_search_bot.i18n import t
from reverse_image_search_bot.utils.tags import pre

from .onboarding import _send_onboarding
from .search import best_match, file_handler
from .utils import _HELP_IMAGE, _detect_file_type


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    assert message and update.effective_chat
    metrics.commands_total.labels(command="id").inc()
    await message.reply_html(pre(json.dumps(update.effective_chat.to_dict(), sort_keys=True, indent=4)))


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.message
    metrics.commands_total.labels(command="start").inc()
    L = get_lang(update)
    chat = update.effective_chat
    if chat and chat.type != "private":
        chat_config = ChatConfig(chat.id)
        if not chat_config.onboarded:
            await _send_onboarding(update, context)
            return
        await update.message.reply_text(
            t("start.group", L),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    else:
        keyboard = ReplyKeyboardMarkup(
            [
                [
                    KeyboardButton("/help", api_kwargs={"icon_custom_emoji_id": "5818947586702184246"}),
                    KeyboardButton("/settings", api_kwargs={"icon_custom_emoji_id": "5818705028424141605"}),
                ],
                [
                    KeyboardButton("/feedback", api_kwargs={"icon_custom_emoji_id": "5443038326535759644"}),
                ],
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await update.message.reply_text(
            t("start.private", L),
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.message
    metrics.commands_total.labels(command="help").inc()
    L = get_lang(update)
    text = (
        f"<b>{t('help.title', L)}</b>\n\n"
        f"<b>{t('help.how_to_use', L)}</b>\n"
        f"{t('help.how_to_use_text', L)}\n\n"
        f"<b>{t('help.commands_title', L)}</b>\n"
        f"{t('help.commands_list', L)}"
    )
    with _HELP_IMAGE.open("rb") as photo:
        await update.message.reply_photo(
            photo,
            caption=text,
            parse_mode=ParseMode.HTML,
            api_kwargs={"show_caption_above_media": True},
        )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.message
    metrics.commands_total.labels(command="search").inc()
    L = get_lang(update)
    orig_message: Message | None = update.message.reply_to_message
    if not orig_message:
        await update.message.reply_text(t("search.reply_required", L))
        return

    await file_handler(update, context, orig_message)


async def group_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle images in group chats — onboard first if needed."""
    assert update.effective_chat
    chat_type = update.effective_chat.type or "unknown"

    # Count every media message received in groups
    msg = update.effective_message
    attachment = msg.effective_attachment if msg else None
    if isinstance(attachment, (list, tuple)):
        attachment = attachment[-1] if attachment else None
    _file_type = _detect_file_type(attachment) if attachment else "unknown"
    metrics.queries_received_total.labels(chat_type=chat_type, file_type=_file_type).inc()

    chat_id = update.effective_chat.id
    chat_config = ChatConfig(chat_id)

    if not chat_config.onboarded:
        await _send_onboarding(update, context)
        return

    if not chat_config.auto_search_enabled and not chat_config.show_buttons:
        return

    await file_handler(update, context)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.callback_query and update.callback_query.data is not None
    query_parts = update.callback_query.data.split(" ")

    if len(query_parts) == 1:
        command, values = query_parts, []
    else:
        command, values = query_parts[0], query_parts[1:]

    match command:
        case "best_match":
            with contextlib.suppress(BadRequest):
                await update.callback_query.answer(show_alert=False)
            await best_match(update, context, values[0])
        case "wait_for":
            await send_wait_for(update, context, values[0])
        case "noop":
            with contextlib.suppress(BadRequest):
                await update.callback_query.answer()
        case _:
            with contextlib.suppress(BadRequest):
                await update.callback_query.answer(t("search.something_went_wrong", get_lang(update)))


async def send_wait_for(update: Update, context: ContextTypes.DEFAULT_TYPE, engine_name: str):
    assert update.callback_query
    L = get_lang(update)
    await update.callback_query.answer(t("search.creating_url", L, engine=engine_name))
