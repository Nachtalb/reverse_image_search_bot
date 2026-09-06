"""The /history command: opens the search-history Mini App."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import ContextTypes

from reverse_image_search_bot import settings
from reverse_image_search_bot.i18n import lang as get_lang
from reverse_image_search_bot.i18n import t

logger = logging.getLogger(__name__)


def webapp_url() -> str | None:
    """Where the Mini App is reachable, or None when it is not configured."""
    if not (settings.WEBAPP_ENABLED and settings.REPORT_BASE_URL):
        return None
    return f"{settings.REPORT_BASE_URL}/app"


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Offer a button that opens the history app.

    A Mini App can only be launched from a button, not from a link, and Telegram
    only allows web_app buttons in PRIVATE chats — which suits history anyway,
    since it is personal.
    """
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return
    L = get_lang(update)
    url = webapp_url()
    if url is None or chat.type != "private":
        await message.reply_text(t("app.unavailable", L))
        return
    await message.reply_text(
        t("app.open_prompt", L),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t("app.title", L), web_app=WebAppInfo(url=url))]]),
    )
