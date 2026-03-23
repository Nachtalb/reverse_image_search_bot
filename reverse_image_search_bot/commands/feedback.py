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

    # Map to track which admin messages correspond to which user chat
    feedback_map: dict[str, int] = context.bot_data.setdefault("feedback_replies", {})

    for admin_id in settings.ADMIN_IDS:
        try:
            sent = await context.bot.send_message(admin_id, admin_text, parse_mode=ParseMode.HTML)
            # Key: "admin_chat_id:message_id" → user chat id
            feedback_map[f"{admin_id}:{sent.message_id}"] = user.id
        except Exception:
            logger.warning("Failed to send feedback to admin %d", admin_id)

    await update.message.reply_text(t("feedback.thanks", L))
    return ConversationHandler.END


async def feedback_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin replies to feedback messages — forward the reply to the original user."""
    assert update.message and update.effective_chat and update.message.reply_to_message

    reply_to = update.message.reply_to_message
    chat_id = update.effective_chat.id
    key = f"{chat_id}:{reply_to.message_id}"

    feedback_map: dict[str, int] = context.bot_data.get("feedback_replies", {})
    user_id = feedback_map.get(key)
    if user_id is None:
        return

    reply_text = update.message.text
    if not reply_text:
        return

    try:
        await context.bot.send_message(
            user_id,
            t("feedback.admin_reply", "en", reply=reply_text),
            parse_mode=ParseMode.HTML,
        )
        await update.message.reply_text(t("feedback.reply_sent", "en"))
    except Exception:
        logger.warning("Failed to send feedback reply to user %d", user_id)
        await update.message.reply_text(t("feedback.reply_failed", "en"))


async def feedback_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> object:
    """Cancel the feedback flow."""
    assert update.message
    L = get_lang(update)
    await update.message.reply_text(t("feedback.cancelled", L))
    return ConversationHandler.END
