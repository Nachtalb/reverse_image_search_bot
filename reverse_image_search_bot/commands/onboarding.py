from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from reverse_image_search_bot.config import ChatConfig
from reverse_image_search_bot.i18n import lang as get_lang
from reverse_image_search_bot.i18n import t


def _is_group(chat_id: int) -> bool:
    return chat_id < 0


async def _send_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the group onboarding prompt with preset choices."""
    L = get_lang(update)
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("onboarding.btn_search_only", L), callback_data="onboard:search_only")],
            [InlineKeyboardButton(t("onboarding.btn_full", L), callback_data="onboard:full")],
            [InlineKeyboardButton(t("onboarding.btn_manual", L), callback_data="onboard:manual")],
            [InlineKeyboardButton(t("onboarding.btn_settings", L), callback_data="onboard:settings")],
        ]
    )
    text = f"{t('onboarding.title', L)}\n\n{t('onboarding.description', L)}"
    msg = update.effective_message or update.message
    assert msg
    await msg.reply_html(text, reply_markup=keyboard)


async def on_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send start message when bot is added to a group."""
    message = update.message
    if not message or not message.new_chat_members:
        return
    for member in message.new_chat_members:
        if member.id == context.bot.id:
            await _send_onboarding(update, context)
            break


async def onboard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle onboarding button presses."""
    from .settings import _is_settings_allowed, _settings_main_keyboard, _settings_main_text

    assert update.effective_chat
    query = update.callback_query
    assert query and query.data is not None
    choice = query.data.split(":", 1)[1]
    chat_id = update.effective_chat.id
    L = get_lang(update)

    if not await _is_settings_allowed(update, context):
        await query.answer(t("settings.admins_only_configure", L), show_alert=True)
        return

    chat_config = ChatConfig(chat_id)
    chat_config.onboarded = True

    if choice == "search_only":
        chat_config.auto_search_enabled = True
        chat_config.show_buttons = False
        await query.edit_message_text(
            t("onboarding.done_search_only", L),
            parse_mode=ParseMode.HTML,
        )
    elif choice == "full":
        chat_config.auto_search_enabled = True
        chat_config.show_buttons = True
        await query.edit_message_text(
            t("onboarding.done_full", L),
            parse_mode=ParseMode.HTML,
        )
    elif choice == "manual":
        chat_config.auto_search_enabled = False
        chat_config.show_buttons = False
        await query.edit_message_text(
            t("onboarding.done_manual", L),
            parse_mode=ParseMode.HTML,
        )
    elif choice == "settings":
        await query.edit_message_text(t("start.opening_settings", L))
        assert update.effective_message
        await update.effective_message.reply_html(
            _settings_main_text(chat_config, L),
            reply_markup=_settings_main_keyboard(chat_config, L),
        )

    await query.answer()
