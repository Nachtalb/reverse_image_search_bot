"""Telegram payment handlers for Star subscriptions."""

from __future__ import annotations

from telegram import LabeledPrice, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from reverse_image_search_bot import metrics
from reverse_image_search_bot.i18n import lang as get_lang
from reverse_image_search_bot.i18n import t
from reverse_image_search_bot.settings import SUBSCRIPTION_STARS_PRICE

from . import db
from .subscription import get_remaining_saucenao, get_remaining_searches, invalidate_premium_cache, is_premium

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
    """Answer pre-checkout queries — always accept valid Star payments."""
    assert update.pre_checkout_query
    await update.pre_checkout_query.answer(ok=True)


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

    await update.message.reply_text(
        t("subscription.payment_success", L),
        parse_mode=ParseMode.HTML,
    )


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
