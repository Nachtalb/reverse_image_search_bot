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
from reverse_image_search_bot.settings import ADMIN_IDS, SUBSCRIPTION_TIERS

from . import db
from .subscription import get_quota_info, invalidate_premium_cache, is_premium

logger = logging.getLogger(__name__)


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /subscribe — show subscription tier buttons."""
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

    buttons = []
    for label, days, price in SUBSCRIPTION_TIERS:
        buttons.append([InlineKeyboardButton(f"⭐ {price} — {label}", callback_data=f"sub_{days}_{price}")])

    await update.message.reply_text(
        t("subscription.choose_plan", L),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def subscribe_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle subscription tier selection — send invoice."""
    assert update.callback_query and update.callback_query.data and update.effective_chat
    query = update.callback_query
    assert query.data is not None
    data: str = query.data
    L = get_lang(update)

    if not data.startswith("sub_"):
        return

    parts = data.split("_")
    if len(parts) != 3:
        await query.answer("Invalid selection.", show_alert=True)
        return

    try:
        days = int(parts[1])
        price = int(parts[2])
    except ValueError:
        await query.answer("Invalid selection.", show_alert=True)
        return

    # Validate against configured tiers
    valid = any(d == days and p == price for _, d, p in SUBSCRIPTION_TIERS)
    if not valid:
        await query.answer("Invalid tier.", show_alert=True)
        return

    label = next((lbl for lbl, d, p in SUBSCRIPTION_TIERS if d == days and p == price), "Premium")
    chat_id = update.effective_chat.id

    await query.answer()
    await context.bot.send_invoice(
        chat_id=query.from_user.id,
        title=t("subscription.invoice_title", L, period=label),
        description=t("subscription.invoice_description", L),
        payload=f"premium_{chat_id}_{days}",
        currency="XTR",
        prices=[LabeledPrice(f"Premium — {label}", price)],
    )


async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Answer pre-checkout queries — validate and accept Star payments."""
    assert update.pre_checkout_query
    query = update.pre_checkout_query

    payload = query.invoice_payload
    if not payload.startswith("premium_"):
        await query.answer(ok=False, error_message="Invalid invoice payload.")
        metrics.subscription_payments_total.labels(status="failed").inc()
        return

    # Validate amount matches a known tier
    valid = any(p == query.total_amount for _, _, p in SUBSCRIPTION_TIERS)
    if not valid:
        await query.answer(ok=False, error_message="Price mismatch. Please try again.")
        metrics.subscription_payments_total.labels(status="failed").inc()
        return

    await query.answer(ok=True)


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process a successful Telegram Stars payment."""
    assert update.message and update.message.successful_payment and update.effective_chat
    payment = update.message.successful_payment
    L = get_lang(update)

    transaction_id = payment.telegram_payment_charge_id
    stars = payment.total_amount
    payload = payment.invoice_payload

    # Extract chat_id and days from payload: premium_{chat_id}_{days}
    parts = payload.split("_")
    if len(parts) >= 3:
        try:
            target_chat_id = int(parts[1])
            days = int(parts[2])
        except ValueError:
            target_chat_id = update.effective_chat.id
            days = next((d for _, d, p in SUBSCRIPTION_TIERS if p == stars), 30)
    else:
        target_chat_id = update.effective_chat.id
        days = next((d for _, d, p in SUBSCRIPTION_TIERS if p == stars), 30)

    db.add_subscription(target_chat_id, days, transaction_id, stars)
    invalidate_premium_cache(target_chat_id)

    metrics.subscription_payments_total.labels(status="success").inc()
    metrics.premium_users_total.set(db.count_premium_chats())

    logger.info(
        "Payment successful: chat_id=%d, days=%d, stars=%d, txn=%s", target_chat_id, days, stars, transaction_id
    )

    await update.message.reply_text(
        t("subscription.payment_success", L, days=str(days)),
        parse_mode=ParseMode.HTML,
    )

    # Notify admins
    user = update.effective_user
    user_info = (
        f"{html_mod.escape(user.full_name)} (<code>{user.id}</code>)" if user else f"<code>{target_chat_id}</code>"
    )
    admin_msg = (
        f"💰 <b>New payment!</b>\n"
        f"User: {user_info}\n"
        f"Chat: <code>{target_chat_id}</code>\n"
        f"Plan: <b>{days} days</b>\n"
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

    info = get_quota_info(chat_id)
    if info["premium"]:
        sub = db.get_active_subscription(chat_id)
        end_date = sub["subscription_end"][:10] if sub else "N/A"
        text = t(
            "subscription.status_premium",
            L,
            end_date=end_date,
            daily_remaining=str(info["daily_remaining"]),
            daily_limit=str(info["daily_limit"]),
            google_remaining=str(info["google_daily_remaining"]),
            google_limit=str(info["google_daily_limit"]),
        )
    else:
        text = t(
            "subscription.status_free",
            L,
            daily_remaining=str(info["daily_remaining"]),
            daily_limit=str(info["daily_limit"]),
            monthly_remaining=str(info["monthly_remaining"]),
            monthly_limit=str(info["monthly_limit"]),
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


async def paysupport_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /paysupport — show payment support contact info (required by Telegram)."""
    assert update.message
    metrics.commands_total.labels(command="paysupport").inc()
    L = get_lang(update)
    await update.message.reply_text(
        t("subscription.paysupport", L), parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def adminrefund_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /adminrefund <chat_id> (admin only) — refund a user's active subscription."""
    assert update.message and update.message.text
    metrics.commands_total.labels(command="adminrefund").inc()

    args = update.message.text.strip().split()
    if len(args) != 2:
        await update.message.reply_text(
            "Usage: <code>/adminrefund &lt;chat_id&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_chat_id = int(args[1])
    except ValueError:
        await update.message.reply_text("Invalid chat_id.")
        return

    sub = db.get_active_subscription(target_chat_id)
    if not sub:
        await update.message.reply_text(
            f"No active subscription for <code>{target_chat_id}</code>.", parse_mode=ParseMode.HTML
        )
        return

    context.user_data["admin_refund_target"] = target_chat_id  # type: ignore[index]
    context.user_data["admin_refund_txn"] = sub["transaction_id"]  # type: ignore[index]

    stars = sub["stars_amount"]
    end = sub["subscription_end"][:10]
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirm refund", callback_data="adminrefund_confirm"),
                InlineKeyboardButton("❌ Cancel", callback_data="adminrefund_cancel"),
            ]
        ]
    )
    await update.message.reply_text(
        f"Refund <b>{stars} ⭐</b> to <code>{target_chat_id}</code>?\n"
        f"Subscription expires: {end}\n"
        f"Txn: <code>{sub['transaction_id'][:32]}…</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def adminrefund_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin refund confirmation/cancellation callbacks."""
    assert update.callback_query and update.callback_query.data is not None
    query = update.callback_query
    assert query.data is not None
    data: str = query.data

    if data == "adminrefund_cancel":
        await query.answer()
        msg = query.message
        if msg and hasattr(msg, "edit_text"):
            await msg.edit_text("Refund cancelled.", parse_mode=ParseMode.HTML)  # type: ignore[union-attr]
        return

    if data == "adminrefund_confirm":
        target_chat_id = context.user_data.get("admin_refund_target") if context.user_data else None
        transaction_id = context.user_data.get("admin_refund_txn") if context.user_data else None

        if not target_chat_id or not transaction_id:
            await query.answer("Refund data expired. Try /adminrefund again.", show_alert=True)
            return

        sub = db.get_active_subscription(target_chat_id)
        if not sub or sub["transaction_id"] != transaction_id:
            await query.answer("Subscription no longer active.", show_alert=True)
            return

        try:
            await context.bot.refund_star_payment(user_id=target_chat_id, telegram_payment_charge_id=transaction_id)
            db.revoke_subscription(target_chat_id, transaction_id)
            invalidate_premium_cache(target_chat_id)
            metrics.subscription_payments_total.labels(status="refunded").inc()
            metrics.premium_users_total.set(db.count_premium_chats())

            logger.info("Admin refund: chat_id=%d, txn=%s, by=%d", target_chat_id, transaction_id, query.from_user.id)

            msg = query.message
            if msg and hasattr(msg, "edit_text"):
                await msg.edit_text(  # type: ignore[union-attr]
                    f"✅ Refunded <b>{sub['stars_amount']} ⭐</b> to <code>{target_chat_id}</code>.",
                    parse_mode=ParseMode.HTML,
                )
            await query.answer()
        except Exception as e:
            logger.error("Admin refund failed: chat_id=%d, txn=%s, error=%s", target_chat_id, transaction_id, e)
            await query.answer(f"Refund failed: {e}", show_alert=True)


async def transactions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /transactions (admin only) — list all subscription transactions."""
    assert update.message
    metrics.commands_total.labels(command="transactions").inc()

    rows = db.list_all_subscriptions()
    if not rows:
        await update.message.reply_text("No transactions found.")
        return

    total_stars = sum(r["stars_amount"] for r in rows if not r["refunded"])
    refunded_stars = sum(r["stars_amount"] for r in rows if r["refunded"])
    active = sum(1 for r in rows if r["active"])
    refunded = sum(1 for r in rows if r["refunded"])

    lines = [
        f"📊 <b>Transactions</b> ({len(rows)} total, {active} active, {refunded} refunded)\n"
        f"💰 {total_stars} ⭐ earned, {refunded_stars} ⭐ refunded\n"
    ]
    for r in rows[-25:]:  # Last 25
        start = r["subscription_start"][:10]
        end = r["subscription_end"][:10]
        chat = r["chat_id"]
        stars = r["stars_amount"]
        status = "🔴 refunded" if r["refunded"] else ("🟢 active" if r["active"] else "⚪ expired")
        lines.append(f"• <code>{chat}</code> | {stars}⭐ | {start}→{end} | {status}")

    if len(rows) > 25:
        lines.append(f"\n<i>(showing last 25 of {len(rows)})</i>")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
