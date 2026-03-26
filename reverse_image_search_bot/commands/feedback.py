from __future__ import annotations

import html
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from reverse_image_search_bot import metrics, settings
from reverse_image_search_bot.i18n import lang as get_lang
from reverse_image_search_bot.i18n import t

logger = logging.getLogger(__name__)

WAITING_FOR_FEEDBACK = 0

# bot_data["feedback_replies"] maps "chat_id:message_id" → target_chat_id
# This allows chaining: admin replies to user, user replies back, etc.


def _feedback_map(context: ContextTypes.DEFAULT_TYPE) -> dict[str, int]:
    return context.bot_data.setdefault("feedback_replies", {})


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
    user_link = f'<a href="tg://user?id={user.id}">{html.escape(user.full_name)}</a>'
    admin_text = t("feedback.admin_message", "en", user=user_link, user_id=user.id, feedback=html.escape(text))

    fmap = _feedback_map(context)

    for admin_id in settings.ADMIN_IDS:
        try:
            sent = await context.bot.send_message(admin_id, admin_text, parse_mode=ParseMode.HTML)
            # Admin message → points to user so admin can reply
            fmap[f"{admin_id}:{sent.message_id}"] = user.id
        except Forbidden:
            logger.warning("Failed to send feedback to admin %d: bot was blocked or never started", admin_id)
        except TelegramError:
            logger.exception("Failed to send feedback to admin %d", admin_id)

    await update.message.reply_text(t("feedback.thanks", L))
    return ConversationHandler.END


async def feedback_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle replies to feedback messages — forwards between admin and user."""
    assert update.message and update.effective_chat and update.message.reply_to_message

    reply_to = update.message.reply_to_message
    chat_id = update.effective_chat.id
    key = f"{chat_id}:{reply_to.message_id}"

    fmap = _feedback_map(context)
    target_id = fmap.get(key)
    if target_id is None:
        return

    reply_text = update.message.text
    if not reply_text:
        return

    is_admin = chat_id in settings.ADMIN_IDS

    if is_admin:
        # Admin → user
        msg_text = t("feedback.admin_reply", "en", reply=html.escape(reply_text))
        success_key = "feedback.reply_sent"
        fail_key = "feedback.reply_failed"
    else:
        # User → admin(s)
        user = update.effective_user
        assert user
        user_link = f'<a href="tg://user?id={user.id}">{html.escape(user.full_name)}</a>'
        msg_text = t("feedback.user_followup", "en", user=user_link, user_id=user.id, feedback=html.escape(reply_text))
        success_key = "feedback.followup_sent"
        fail_key = "feedback.followup_failed"

    if is_admin:
        # Send to the specific user
        try:
            sent = await context.bot.send_message(target_id, msg_text, parse_mode=ParseMode.HTML)
            # Store reverse mapping so user can reply back
            fmap[f"{target_id}:{sent.message_id}"] = chat_id
            await update.message.reply_text(t(success_key, "en"))
        except Forbidden:
            logger.warning(
                "Failed to send feedback reply to user %d: user blocked the bot or never started it", target_id
            )
            await update.message.reply_text(
                t(fail_key, "en") + "\n\n🟠 <i>Reason: user has blocked the bot or never started it.</i>",
                parse_mode=ParseMode.HTML,
            )
        except TelegramError as e:
            logger.exception("Failed to send feedback reply to user %d", target_id)
            await update.message.reply_text(
                t(fail_key, "en") + f"\n\n🔴 <i>Error: {html.escape(str(e))}</i>",
                parse_mode=ParseMode.HTML,
            )
    else:
        # User replying — send to all admins
        for admin_id in settings.ADMIN_IDS:
            try:
                sent = await context.bot.send_message(admin_id, msg_text, parse_mode=ParseMode.HTML)
                fmap[f"{admin_id}:{sent.message_id}"] = chat_id
            except Forbidden:
                logger.warning("Failed to send user followup to admin %d: bot was blocked or never started", admin_id)
            except TelegramError:
                logger.exception("Failed to send user followup to admin %d", admin_id)
        await update.message.reply_text(t(success_key, "en"))


async def feedback_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> object:
    """Cancel the feedback flow."""
    assert update.message
    L = get_lang(update)
    await update.message.reply_text(t("feedback.cancelled", L))
    return ConversationHandler.END
