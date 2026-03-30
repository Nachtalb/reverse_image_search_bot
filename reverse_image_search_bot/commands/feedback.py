from __future__ import annotations

import html
import logging
from dataclasses import dataclass

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from reverse_image_search_bot import metrics, settings
from reverse_image_search_bot.i18n import lang as get_lang
from reverse_image_search_bot.i18n import t

logger = logging.getLogger(__name__)

WAITING_FOR_FEEDBACK = 0

# bot_data["feedback_replies"] maps "chat_id:message_id" → FeedbackTarget | int (legacy)
# This allows chaining: admin replies to user, user replies back, etc.


@dataclass
class FeedbackTarget:
    """Target info for a feedback reply."""

    user_id: int
    chat_id: int  # the chat where the user sent /feedback


def _feedback_map(context: ContextTypes.DEFAULT_TYPE) -> dict[str, FeedbackTarget | int]:
    return context.bot_data.setdefault("feedback_replies", {})


def _resolve_target(value: FeedbackTarget | int) -> FeedbackTarget:
    """Handle legacy int entries (user_id only, no chat fallback)."""
    if isinstance(value, int):
        return FeedbackTarget(user_id=value, chat_id=value)
    return value


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

    feedback_chat_id = update.effective_chat.id if update.effective_chat else user.id

    for admin_id in settings.ADMIN_IDS:
        try:
            sent = await context.bot.send_message(admin_id, admin_text, parse_mode=ParseMode.HTML)
            # Admin message → points to user so admin can reply
            fmap[f"{admin_id}:{sent.message_id}"] = FeedbackTarget(user_id=user.id, chat_id=feedback_chat_id)
        except Forbidden:
            logger.warning("Failed to send feedback to admin %d: bot was blocked or never started", admin_id)
        except TelegramError:
            logger.exception("Failed to send feedback to admin %d", admin_id)

    await update.message.reply_text(t("feedback.thanks", L))
    return ConversationHandler.END


async def _send_to_user_or_chat(
    context: ContextTypes.DEFAULT_TYPE,
    target: FeedbackTarget,
    msg_text: str,
    fmap: dict[str, FeedbackTarget | int],
    admin_chat_id: int,
) -> tuple[bool, str]:
    """Try sending to user DM first, fall back to original chat.

    Returns (success, detail) for the admin confirmation message.
    """
    # Try DM first
    try:
        sent = await context.bot.send_message(target.user_id, msg_text, parse_mode=ParseMode.HTML)
        fmap[f"{target.user_id}:{sent.message_id}"] = FeedbackTarget(user_id=admin_chat_id, chat_id=admin_chat_id)
        return True, "dm"
    except Forbidden:
        logger.info("DM to user %d forbidden, trying group chat %d", target.user_id, target.chat_id)
    except TelegramError:
        logger.exception("DM to user %d failed, trying group chat %d", target.user_id, target.chat_id)

    # Fall back to group chat (skip if same as user_id — means it was a DM originally or legacy entry)
    if target.chat_id == target.user_id:
        return False, "blocked"

    try:
        sent = await context.bot.send_message(target.chat_id, msg_text, parse_mode=ParseMode.HTML)
        fmap[f"{target.chat_id}:{sent.message_id}"] = FeedbackTarget(user_id=admin_chat_id, chat_id=admin_chat_id)
        return True, "group"
    except TelegramError:
        logger.exception("Failed to send feedback reply to group chat %d", target.chat_id)
        return False, "both_failed"


async def feedback_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle replies to feedback messages — forwards between admin and user."""
    assert update.message and update.effective_chat and update.message.reply_to_message

    reply_to = update.message.reply_to_message
    chat_id = update.effective_chat.id
    key = f"{chat_id}:{reply_to.message_id}"

    fmap = _feedback_map(context)
    raw_target = fmap.get(key)
    if raw_target is None:
        return

    reply_text = update.message.text
    if not reply_text:
        return

    is_admin = chat_id in settings.ADMIN_IDS

    if is_admin:
        # Admin → user
        target = _resolve_target(raw_target)
        msg_text = t("feedback.admin_reply", "en", reply=html.escape(reply_text))
        success_key = "feedback.reply_sent"
        fail_key = "feedback.reply_failed"

        ok, detail = await _send_to_user_or_chat(context, target, msg_text, fmap, chat_id)
        if ok:
            suffix = " (via group chat)" if detail == "group" else ""
            await update.message.reply_text(t(success_key, "en") + suffix)
        elif detail == "blocked":
            await update.message.reply_text(
                t(fail_key, "en")
                + "\n\n🟠 <i>User has blocked the bot or never started it (no group fallback available).</i>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text(
                t(fail_key, "en") + "\n\n🔴 <i>Failed to reach user via DM and group chat.</i>",
                parse_mode=ParseMode.HTML,
            )
    else:
        # User → admin(s)
        user = update.effective_user
        assert user
        user_link = f'<a href="tg://user?id={user.id}">{html.escape(user.full_name)}</a>'
        msg_text = t("feedback.user_followup", "en", user=user_link, user_id=user.id, feedback=html.escape(reply_text))
        success_key = "feedback.followup_sent"
        feedback_chat_id = update.effective_chat.id

        for admin_id in settings.ADMIN_IDS:
            try:
                sent = await context.bot.send_message(admin_id, msg_text, parse_mode=ParseMode.HTML)
                fmap[f"{admin_id}:{sent.message_id}"] = FeedbackTarget(user_id=user.id, chat_id=feedback_chat_id)
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
