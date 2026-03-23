from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from reverse_image_search_bot import metrics, settings
from reverse_image_search_bot.i18n import lang as get_lang
from reverse_image_search_bot.i18n import t

logger = logging.getLogger(__name__)

WAITING_FOR_FEEDBACK = 0


async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> object:
    """Entry point: /feedback — ask user to type their feedback."""
    assert update.message
    metrics.commands_total.labels(command="feedback").inc()
    L = get_lang(update)
    await update.message.reply_text(t("feedback.prompt", L))
    return WAITING_FOR_FEEDBACK


async def feedback_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> object:
    """Receive the feedback text and forward it to admins."""
    assert update.message and update.effective_user
    L = get_lang(update)
    text = update.message.text
    if not text or not text.strip():
        await update.message.reply_text(t("feedback.empty", L))
        return WAITING_FOR_FEEDBACK

    user = update.effective_user
    user_link = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    admin_text = t("feedback.admin_message", "en", user=user_link, user_id=user.id, feedback=text)

    for admin_id in settings.ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, admin_text, parse_mode=ParseMode.HTML)
        except Exception:
            logger.warning("Failed to send feedback to admin %d", admin_id)

    await update.message.reply_text(t("feedback.thanks", L))
    return ConversationHandler.END


async def feedback_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> object:
    """Cancel the feedback flow."""
    assert update.message
    L = get_lang(update)
    await update.message.reply_text(t("feedback.cancelled", L))
    return ConversationHandler.END
