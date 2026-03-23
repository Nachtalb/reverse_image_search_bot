"""Telegram payment handlers for Star subscriptions."""

from __future__ import annotations

import html as html_mod
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from reverse_image_search_bot import metrics
from reverse_image_search_bot.i18n import lang as get_lang
from reverse_image_search_bot.i18n import t
from reverse_image_search_bot.settings import ADMIN_IDS, SUBSCRIPTION_STARS_PRICE

from . import db
from .subscription import get_remaining_saucenao, get_remaining_searches, invalidate_premium_cache, is_premium

logger = logging.getLogger(__name__)

_SUBSCRIPTION_DAYS = 30


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /subscribe — send a Telegram Stars invoice."""
    assert update.message and update.effective_chat
    metrics.commands_total.labels(command="subscribe").inc()
    L = get_lang(update)
    chat_id = update.effective_chat.id

    if is_premium(chat_id):
        sub = db.get_active_subscription(chat_id)
        end_date = sub["subscription_end"][:10] if sub else "?"
        await update.message.reply_text(
            t("subscription.already_premium", L, end_date=end_date),
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_invoice(
        title=t("subscription.invoice_title", L),
        description=t("subscription.invoice_description", L),
        payload=f"premium_{chat_id}",
        currency="XTR",
        prices=[LabeledPrice(t("subscription.invoice_label", L), SUBSCRIPTION_STARS_PRICE)],
    )


async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Answer pre-checkout queries — validate and accept Star payments."""
    assert update.pre_checkout_query
    query = update.pre_checkout_query

    # Validate payload format
    payload = query.invoice_payload
    if not payload.startswith("premium_"):
        await query.answer(ok=False, error_message="Invalid invoice payload.")
        metrics.subscription_payments_total.labels(status="failed").inc()
        return

    # Validate amount
    if query.total_amount != SUBSCRIPTION_STARS_PRICE:
        await query.answer(ok=False, error_message="Price mismatch. Please try again.")
        metrics.subscription_payments_total.labels(status="failed").inc()
        return

    await query.answer(ok=True)


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process a successful Telegram Stars payment."""
    assert update.message and update.message.successful_payment and update.effective_chat
    payment = update.message.successful_payment
    L = get_lang(update)
    chat_id = update.effective_chat.id

    transaction_id = payment.telegram_payment_charge_id
    stars = payment.total_amount

    db.add_subscription(chat_id, _SUBSCRIPTION_DAYS, transaction_id, stars)
    invalidate_premium_cache(chat_id)

    metrics.subscription_payments_total.labels(status="success").inc()
    metrics.premium_users_total.set(db.count_premium_chats())

    logger.info("Payment successful: chat_id=%d, stars=%d, txn=%s", chat_id, stars, transaction_id)

    await update.message.reply_text(
        t("subscription.payment_success", L),
        parse_mode=ParseMode.HTML,
    )

    # Notify admins
    user = update.effective_user
    user_info = f"{html_mod.escape(user.full_name)} (<code>{user.id}</code>)" if user else f"<code>{chat_id}</code>"
    admin_msg = (
        f"💰 <b>New payment!</b>\n"
        f"User: {user_info}\n"
        f"Chat: <code>{chat_id}</code>\n"
        f"Amount: <b>{stars} ⭐</b>\n"
        f"Txn: <code>{transaction_id}</code>"
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, admin_msg, parse_mode=ParseMode.HTML)
        except Exception:
            logger.warning("Failed to notify admin %d of payment", admin_id)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status — show subscription info and remaining quota."""
    assert update.message and update.effective_chat
    metrics.commands_total.labels(command="status").inc()
    L = get_lang(update)
    chat_id = update.effective_chat.id

    if is_premium(chat_id):
        sub = db.get_active_subscription(chat_id)
        end_date = sub["subscription_end"][:10] if sub else "N/A"
        text = t("subscription.status_premium", L, end_date=end_date)
    else:
        remaining, limit = get_remaining_searches(chat_id)
        saucenao_remaining = get_remaining_saucenao(chat_id)
        text = t(
            "subscription.status_free",
            L,
            remaining=str(remaining),
            limit=str(limit),
            saucenao_remaining=str(saucenao_remaining),
        )

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def terms_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /terms — show terms of service."""
    assert update.message
    metrics.commands_total.labels(command="terms").inc()
    L = get_lang(update)
    await update.message.reply_text(
        t("subscription.terms", L), parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /support — show support contact info."""
    assert update.message
    metrics.commands_total.labels(command="support").inc()
    L = get_lang(update)
    await update.message.reply_text(
        t("subscription.support", L), parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def refund_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /refund — offer to refund the last subscription payment."""
    assert update.message and update.effective_chat
    metrics.commands_total.labels(command="refund").inc()
    L = get_lang(update)
    chat_id = update.effective_chat.id

    sub = db.get_active_subscription(chat_id)
    if not sub:
        await update.message.reply_text(t("subscription.refund_no_subscription", L), parse_mode=ParseMode.HTML)
        return

    # Store txn ID in user_data since callback_data has a 64-byte limit
    context.user_data["pending_refund_txn"] = sub["transaction_id"]  # type: ignore[index]
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes, refund", callback_data="refund_confirm"),
                InlineKeyboardButton("❌ Cancel", callback_data="refund_cancel"),
            ]
        ]
    )
    await update.message.reply_text(
        t("subscription.refund_confirm", L), parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def refund_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle refund confirmation/cancellation callbacks."""
    assert update.callback_query and update.callback_query.data is not None and update.effective_chat
    query = update.callback_query
    assert query.data is not None
    data: str = query.data
    L = get_lang(update)

    if data == "refund_cancel":
        await query.answer()
        msg = query.message
        if msg and hasattr(msg, "edit_text"):
            await msg.edit_text(t("subscription.refund_cancelled", L), parse_mode=ParseMode.HTML)  # type: ignore[union-attr]
        return

    if data == "refund_confirm":
        transaction_id = context.user_data.get("pending_refund_txn") if context.user_data else None
        chat_id = update.effective_chat.id
        sub = db.get_active_subscription(chat_id)

        if not sub or not transaction_id or sub["transaction_id"] != transaction_id:
            await query.answer(t("subscription.refund_no_subscription", L), show_alert=True)
            return

        try:
            # Telegram Stars refund API
            user_id = query.from_user.id
            await context.bot.refund_star_payment(user_id=user_id, telegram_payment_charge_id=transaction_id)
            db.revoke_subscription(chat_id, transaction_id)
            invalidate_premium_cache(chat_id)
            metrics.subscription_payments_total.labels(status="refunded").inc()
            metrics.premium_users_total.set(db.count_premium_chats())

            logger.info("Refund processed: chat_id=%d, txn=%s", chat_id, transaction_id)

            msg = query.message
            if msg and hasattr(msg, "edit_text"):
                await msg.edit_text(  # type: ignore[union-attr]
                    t("subscription.refund_success", L, amount=str(sub["stars_amount"])),
                    parse_mode=ParseMode.HTML,
                )
            await query.answer()
        except Exception as e:
            logger.error("Refund failed: chat_id=%d, txn=%s, error=%s", chat_id, transaction_id, e)
            await query.answer(f"Refund failed: {e}", show_alert=True)


async def transactions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /transactions (admin only) — list all subscription transactions."""
    assert update.message
    metrics.commands_total.labels(command="transactions").inc()

    rows = db.list_all_subscriptions()
    if not rows:
        await update.message.reply_text("No transactions found.")
        return

    total_stars = sum(r["stars_amount"] for r in rows)
    active = sum(1 for r in rows if not r.get("revoked", False))

    lines = [f"📊 <b>Transactions</b> ({len(rows)} total, {active} active, {total_stars} ⭐ total)\n"]
    for r in rows[-25:]:  # Last 25
        start = r["subscription_start"][:10]
        end = r["subscription_end"][:10]
        chat = r["chat_id"]
        stars = r["stars_amount"]
        txn = r["transaction_id"][:16]
        lines.append(f"• <code>{chat}</code> | {stars}⭐ | {start}→{end} | <code>{txn}…</code>")

    if len(rows) > 25:
        lines.append(f"\n<i>(showing last 25 of {len(rows)})</i>")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
