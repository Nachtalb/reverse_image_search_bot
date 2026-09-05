"""User-facing data commands: /privacy, /takeout, /delete."""

from __future__ import annotations

from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from reverse_image_search_bot import metrics

_PRIVACY_TEXT = (Path(__file__).parent.parent / "texts" / "privacy.html").read_text(encoding="utf-8")


async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    metrics.commands_total.labels(command="privacy").inc()
    await message.reply_text(_PRIVACY_TEXT, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
