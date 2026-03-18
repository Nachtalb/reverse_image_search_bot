from __future__ import annotations

import contextlib

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from reverse_image_search_bot import metrics
from reverse_image_search_bot.config import ChatConfig
from reverse_image_search_bot.engines import engines
from reverse_image_search_bot.i18n import available_languages, t
from reverse_image_search_bot.i18n import lang as get_lang
from reverse_image_search_bot.utils import chunks

from .onboarding import _is_group
from .utils import _LANG_NAMES


async def _is_settings_allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Allow settings changes in private chats always; in groups only for admins."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False
    if chat.type == "private":
        return True
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("creator", "administrator")
    except Exception:
        return False


def _settings_main_text(chat_config: ChatConfig, L: str = "en") -> str:
    return f"{t('settings.title', L)}\n{t('settings.subtitle', L)}"


def _settings_main_keyboard(chat_config: ChatConfig, L: str = "en") -> InlineKeyboardMarkup:
    auto = "✅" if chat_config.auto_search_enabled else "❌"
    buttons = "✅" if chat_config.show_buttons else "❌"
    as_engines_label = (
        t("settings.toggles.auto_search_engines", L)
        if chat_config.auto_search_enabled
        else t("settings.toggles.auto_search_engines_locked", L)
    )
    as_engines_cb = (
        "settings:menu:auto_search_engines"
        if chat_config.auto_search_enabled
        else "settings:disabled:auto_search_engines"
    )
    btn_engines_label = (
        t("settings.toggles.button_engines", L)
        if chat_config.show_buttons
        else t("settings.toggles.button_engines_locked", L)
    )
    btn_engines_cb = "settings:menu:button_engines" if chat_config.show_buttons else "settings:disabled:button_engines"

    lang_display = _LANG_NAMES.get(chat_config.language or "auto", chat_config.language or "auto")

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("settings.toggles.auto_search", L, status=auto), callback_data="settings:toggle:auto_search"
                )
            ],
            [
                InlineKeyboardButton(
                    t("settings.toggles.show_buttons", L, status=buttons), callback_data="settings:toggle:show_buttons"
                )
            ],
            [InlineKeyboardButton(as_engines_label, callback_data=as_engines_cb)],
            [InlineKeyboardButton(btn_engines_label, callback_data=btn_engines_cb)],
            [
                InlineKeyboardButton(
                    t("settings.toggles.language", L, language=lang_display),
                    callback_data="settings:menu:language",
                )
            ],
        ]
    )


def _settings_engines_keyboard(chat_config: ChatConfig, menu: str, L: str = "en") -> InlineKeyboardMarkup:
    """Build a per-engine toggle keyboard for either 'auto_search_engines' or 'button_engines'."""
    rows: list[list[InlineKeyboardButton]] = []

    if menu == "auto_search_engines":
        enabled = chat_config.auto_search_engines
        cb_prefix = "settings:toggle:auto_search_engine"
        relevant = [e for e in engines if e.best_match_implemented]
    else:
        enabled = chat_config.button_engines
        cb_prefix = "settings:toggle:button_engine"
        relevant = list(engines)
        bm = "✅" if chat_config.show_best_match else "❌"
        link = "✅" if chat_config.show_link else "❌"
        rows.append(
            [
                InlineKeyboardButton(
                    t("settings.toggles.best_match_btn", L, status=bm), callback_data="settings:toggle:show_best_match"
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    t("settings.toggles.show_link_btn", L, status=link), callback_data="settings:toggle:show_link"
                )
            ]
        )

    engine_btns = [
        InlineKeyboardButton(
            f"{'✅' if (enabled is None or e.name in enabled) else '❌'} {e.name}",
            callback_data=f"{cb_prefix}:{e.name}",
        )
        for e in relevant
    ]
    rows.extend(chunks(engine_btns, 2))
    rows.append([InlineKeyboardButton(t("settings.toggles.back", L), callback_data="settings:back")])
    return InlineKeyboardMarkup(rows)


def _settings_language_keyboard(chat_config: ChatConfig, L: str = "en") -> InlineKeyboardMarkup:
    """Build a language selection keyboard."""
    current = chat_config.language
    rows: list[list[InlineKeyboardButton]] = []

    # Auto option
    check = "✅ " if current is None else ""
    rows.append([InlineKeyboardButton(f"{check}{_LANG_NAMES['auto']}", callback_data="settings:lang:auto")])

    # Language options in pairs
    lang_btns = []
    for lang_code in available_languages():
        check = "✅ " if current == lang_code else ""
        display = _LANG_NAMES.get(lang_code, lang_code)
        lang_btns.append(InlineKeyboardButton(f"{check}{display}", callback_data=f"settings:lang:{lang_code}"))
    rows.extend(chunks(lang_btns, 2))

    rows.append([InlineKeyboardButton(t("settings.toggles.back", L), callback_data="settings:back")])
    return InlineKeyboardMarkup(rows)


def _button_count(chat_config: ChatConfig, excluding_engine: str | None = None) -> int:
    """Count active buttons (best match + link + engine buttons). Used to enforce minimum of 1."""
    count = int(chat_config.show_best_match) + int(chat_config.show_link)
    all_names = [e.name for e in engines]
    active = chat_config.button_engines if chat_config.button_engines is not None else all_names
    for name in active:
        if name != excluding_engine:
            count += 1
    return count


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.message and update.effective_chat
    metrics.commands_total.labels(command="settings").inc()
    L = get_lang(update)

    if not await _is_settings_allowed(update, context):
        await update.message.reply_text(t("settings.admins_only", L))
        return

    chat_config = ChatConfig(update.effective_chat.id)
    if _is_group(update.effective_chat.id) and not chat_config.onboarded:
        chat_config.onboarded = True
    await update.message.reply_html(
        _settings_main_text(chat_config, L),
        reply_markup=_settings_main_keyboard(chat_config, L),
    )


async def settings_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    assert query and query.data is not None
    data = query.data
    L = get_lang(update)

    if data == "settings:noop":
        await query.answer()
        return
    if data.startswith("settings:disabled:"):
        field = data.split(":", 2)[2]
        if field in ("auto_search_engines", "button_engines"):
            key = f"settings.disabled_reasons.{field}"
        else:
            key = "settings.disabled_reasons.default"
        reason = t(key, L)
        await query.answer(reason, show_alert=False)
        return

    if not await _is_settings_allowed(update, context):
        await query.answer(t("settings.admins_only_change", L), show_alert=True)
        return

    assert update.effective_chat
    chat_config = ChatConfig(update.effective_chat.id)
    parts = data.split(":", 2)
    action = parts[1] if len(parts) > 1 else ""
    value = parts[2] if len(parts) > 2 else ""

    is_group = _is_group(update.effective_chat.id)

    if action == "lang":
        # Language selection
        if value == "auto":
            chat_config.language = None
        else:
            chat_config.language = value
        # Re-resolve language after change
        L = get_lang(update)
        with contextlib.suppress(TelegramError):
            await query.edit_message_text(
                _settings_main_text(chat_config, L),
                parse_mode="HTML",
                reply_markup=_settings_main_keyboard(chat_config, L),
            )
        await query.answer()
        return

    if action == "toggle":
        if value == "auto_search":
            if not is_group and chat_config.auto_search_enabled and not chat_config.show_buttons:
                await query.answer(t("settings.warnings.enable_buttons_first", L), show_alert=True)
                return
            chat_config.auto_search_enabled = not chat_config.auto_search_enabled
        elif value == "show_buttons":
            if not is_group and chat_config.show_buttons and not chat_config.auto_search_enabled:
                await query.answer(t("settings.warnings.enable_autosearch_first", L), show_alert=True)
                return
            chat_config.show_buttons = not chat_config.show_buttons
        elif value == "show_best_match":
            if chat_config.show_best_match and _button_count(chat_config) <= 1:
                await query.answer(t("settings.warnings.min_one_button", L), show_alert=True)
                return
            chat_config.show_best_match = not chat_config.show_best_match
            action = "disabled" if not chat_config.show_best_match else "enabled"
            metrics.button_toggle_total.labels(button="best_match", action=action).inc()
        elif value == "show_link":
            if chat_config.show_link and _button_count(chat_config) <= 1:
                await query.answer(t("settings.warnings.min_one_button", L), show_alert=True)
                return
            chat_config.show_link = not chat_config.show_link
            action = "disabled" if not chat_config.show_link else "enabled"
            metrics.button_toggle_total.labels(button="show_link", action=action).inc()
        elif value.startswith("auto_search_engine:"):
            engine_name = value[len("auto_search_engine:") :]
            relevant = [e.name for e in engines if e.best_match_implemented]
            current = chat_config.auto_search_engines
            if current is None:
                current = relevant[:]
            if engine_name in current:
                if len(current) == 1:
                    await query.answer(t("settings.warnings.min_one_engine", L), show_alert=True)
                    return
                current.remove(engine_name)
                metrics.engine_manual_toggle_total.labels(
                    engine=engine_name, menu="auto_search", action="disabled"
                ).inc()
            else:
                current.append(engine_name)
                chat_config.reset_engine_counter(engine_name)
                metrics.engine_manual_toggle_total.labels(
                    engine=engine_name, menu="auto_search", action="enabled"
                ).inc()
            chat_config.auto_search_engines = None if set(current) >= set(relevant) else current
        elif value.startswith("button_engine:"):
            engine_name = value[len("button_engine:") :]
            all_names = [e.name for e in engines]
            current = chat_config.button_engines
            if current is None:
                current = all_names[:]
            if engine_name in current:
                if _button_count(chat_config, excluding_engine=engine_name) < 1:
                    await query.answer(t("settings.warnings.min_one_button", L), show_alert=True)
                    return
                current.remove(engine_name)
                metrics.engine_manual_toggle_total.labels(engine=engine_name, menu="button", action="disabled").inc()
            else:
                current.append(engine_name)
                metrics.engine_manual_toggle_total.labels(engine=engine_name, menu="button", action="enabled").inc()
            chat_config.button_engines = None if set(current) >= set(all_names) else current

        # Re-render appropriate menu
        if value.startswith("auto_search_engine:"):
            with contextlib.suppress(TelegramError):
                await query.edit_message_reply_markup(
                    reply_markup=_settings_engines_keyboard(chat_config, "auto_search_engines", L)
                )
        elif value.startswith("button_engine:") or value in ("show_link", "show_best_match"):
            with contextlib.suppress(TelegramError):
                await query.edit_message_reply_markup(
                    reply_markup=_settings_engines_keyboard(chat_config, "button_engines", L)
                )
        else:
            with contextlib.suppress(TelegramError):
                await query.edit_message_reply_markup(reply_markup=_settings_main_keyboard(chat_config, L))

    elif action == "menu":
        if value == "language":
            with contextlib.suppress(TelegramError):
                await query.edit_message_reply_markup(reply_markup=_settings_language_keyboard(chat_config, L))
        else:
            with contextlib.suppress(TelegramError):
                await query.edit_message_reply_markup(reply_markup=_settings_engines_keyboard(chat_config, value, L))

    elif action == "back":
        with contextlib.suppress(TelegramError):
            await query.edit_message_text(
                _settings_main_text(chat_config, L),
                parse_mode="HTML",
                reply_markup=_settings_main_keyboard(chat_config, L),
            )

    await query.answer()
