from __future__ import annotations

import asyncio
import contextlib
import html as html_mod
import io
import json
from concurrent.futures import ProcessPoolExecutor
from logging import getLogger
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import time

from PIL import Image
from telegram import (
    Animation,
    Document,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    PhotoSize,
    ReplyKeyboardMarkup,
    Sticker,
    Update,
    Video,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes
from yarl import URL

from reverse_image_search_bot import metrics
from reverse_image_search_bot.config import ChatConfig
from reverse_image_search_bot.engines import engines
from reverse_image_search_bot.engines.errors import EngineError, RateLimitError
from reverse_image_search_bot.engines.generic import GenericRISEngine, PreWorkEngine
from reverse_image_search_bot.engines.types import MetaData, ResultData
from reverse_image_search_bot.i18n import available_languages, t, translate_field
from reverse_image_search_bot.i18n import lang as get_lang
from reverse_image_search_bot.settings import ADMIN_IDS
from reverse_image_search_bot.uploaders import uploader
from reverse_image_search_bot.utils import chunks, upload_file
from reverse_image_search_bot.utils.tags import a, b, code, hidden_a, pre, title

logger = getLogger("BEST MATCH")
last_used: dict[int, float] = {}

_process_executor = ProcessPoolExecutor(max_workers=2)


def _extract_video_frame(video_path: str) -> bytes:
    """Extract the first frame from a video as JPEG bytes. Runs in a separate process."""
    from moviepy.video.io.VideoFileClip import VideoFileClip
    from PIL import Image

    with VideoFileClip(video_path, audio=False) as clip:
        frame = clip.get_frame(0)
    buf = io.BytesIO()
    Image.fromarray(frame, "RGB").save(buf, "jpeg")
    return buf.getvalue()


# Telegram Bot API file download limit (20 MB)
MAX_TELEGRAM_FILE_SIZE = 20 * 1024 * 1024

_LANG_NAMES: dict[str, str] = {
    "auto": "🌐 Auto",
    "en": "🇬🇧 English",
    "ru": "🇷🇺 Русский",
    "zh": "🇨🇳 中文",
    "es": "🇪🇸 Español",
    "it": "🇮🇹 Italiano",
    "ar": "🇸🇦 العربية",
    "ja": "🇯🇵 日本語",
    "de": "🇩🇪 Deutsch",
    "fr": "🇫🇷 Français",
    "pt": "🇧🇷 Português",
}


# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Commands
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    assert message and update.effective_chat
    metrics.commands_total.labels(command="id").inc()
    await message.reply_html(pre(json.dumps(update.effective_chat.to_dict(), sort_keys=True, indent=4)))


# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Settings (per-chat inline keyboard UI)
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #


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


_LOCAL = Path(__file__).parent
_HELP_IMAGE = _LOCAL / "images/help.jpg"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.message
    metrics.commands_total.labels(command="start").inc()
    L = get_lang(update)
    chat = update.effective_chat
    if chat and chat.type != "private":
        chat_config = ChatConfig(chat.id)
        if not chat_config.onboarded:
            await _send_onboarding(update, context)
            return
        await update.message.reply_text(
            t("start.group", L),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    else:
        keyboard = ReplyKeyboardMarkup(
            [
                [
                    KeyboardButton("/help", api_kwargs={"icon_custom_emoji_id": "5818947586702184246"}),
                    KeyboardButton("/settings", api_kwargs={"icon_custom_emoji_id": "5818705028424141605"}),
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await update.message.reply_text(
            t("start.private", L),
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def on_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send start message when bot is added to a group."""
    message = update.message
    if not message or not message.new_chat_members:
        return
    for member in message.new_chat_members:
        if member.id == context.bot.id:
            await _send_onboarding(update, context)
            break


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


def _is_group(chat_id: int) -> bool:
    return chat_id < 0


async def onboard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle onboarding button presses."""
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


async def group_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle images in group chats — onboard first if needed."""
    assert update.effective_chat
    chat_id = update.effective_chat.id
    chat_config = ChatConfig(chat_id)

    if not chat_config.onboarded:
        await _send_onboarding(update, context)
        return

    if not chat_config.auto_search_enabled and not chat_config.show_buttons:
        return

    await file_handler(update, context)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.message
    metrics.commands_total.labels(command="help").inc()
    L = get_lang(update)
    text = (
        f"<b>{t('help.title', L)}</b>\n\n"
        f"<b>{t('help.how_to_use', L)}</b>\n"
        f"{t('help.how_to_use_text', L)}\n\n"
        f"<b>{t('help.commands_title', L)}</b>\n"
        f"{t('help.commands_list', L)}"
    )
    with _HELP_IMAGE.open("rb") as photo:
        await update.message.reply_photo(
            photo,
            caption=text,
            parse_mode=ParseMode.HTML,
            api_kwargs={"show_caption_above_media": True},
        )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.message
    metrics.commands_total.labels(command="search").inc()
    L = get_lang(update)
    orig_message: Message | None = update.message.reply_to_message
    if not orig_message:
        await update.message.reply_text(t("search.reply_required", L))
        return

    await file_handler(update, context, orig_message)


async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, message: Message | None = None):
    message = message or update.effective_message
    if not message:
        return
    assert update.effective_chat

    user = message.from_user
    if not user:
        return
    L = get_lang(update)
    if user.id in context.bot_data.get("banned_users", []):
        await message.reply_text(t("search.files.banned", L))
        return

    await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)

    attachment = message.effective_attachment
    if isinstance(attachment, (list, tuple)):
        attachment = attachment[-1]

    # Determine file type for metrics
    if isinstance(attachment, Sticker):
        file_type = "sticker"
    elif isinstance(attachment, Animation):
        file_type = "gif"
    elif isinstance(attachment, Video):
        file_type = "video"
    elif isinstance(attachment, PhotoSize):
        file_type = "photo"
    elif isinstance(attachment, Document):
        file_type = "document"
    else:
        file_type = "unknown"

    metrics.files_received_total.labels(file_type=file_type).inc()
    file_size = getattr(attachment, "file_size", None)
    if file_size:
        metrics.file_size_bytes.labels(file_type=file_type).observe(float(file_size))

    language = getattr(user, "language_code", None) or "unknown"

    try:
        image_url = None
        error = None
        mime = attachment.mime_type if isinstance(attachment, Document) else None
        logger.info(
            "file_handler: type=%s, mime=%s, file_type=%s",
            type(attachment).__name__,
            mime,
            file_type,
        )
        try:
            if (
                (isinstance(attachment, Document) and mime and mime.startswith("video"))
                or isinstance(attachment, (Video, Animation))
                or (isinstance(attachment, Sticker) and attachment.is_video)
            ):
                search_type = "video_frame" if isinstance(attachment, Video) else file_type
                image_url = await video_to_url(attachment)
            elif (isinstance(attachment, Document) and mime and mime.endswith(("jpeg", "png", "webp"))) or isinstance(
                attachment, (PhotoSize, Sticker)
            ):
                if isinstance(attachment, Sticker) and attachment.is_animated:
                    await message.reply_text(t("search.files.animated_not_supported", L))
                    return
                search_type = file_type
                image_url = await image_to_url(attachment)
        except ValueError as e:
            await message.reply_text(str(e))
            return
        except Exception as e:
            error = e

        if not image_url:
            await message.reply_text(t("search.files.format_not_supported", L))
            if error is not None:
                raise error
            return

        # Track usage metrics
        metrics.searches_total.labels(type=search_type, language=language).inc()
        metrics.searches_by_user_total.labels(user_id=str(user.id)).inc()

        # Run general_image_search and best_match concurrently
        general_done = asyncio.Event()
        general_task = asyncio.create_task(general_image_search(update, image_url, general_done))
        # Suppress "Task exception was never retrieved" — general_image_search
        # handles its own errors internally; this just marks the exception as seen.
        general_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

        try:
            chat_config = ChatConfig(update.effective_chat.id)
            if chat_config.auto_search_enabled:
                await best_match(update, context, image_url, general_done)
            else:
                await general_task
        except Exception:
            general_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await general_task
            raise

    except Exception:
        await message.reply_text(t("search.generic_error", L))
        raise


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.callback_query and update.callback_query.data is not None
    query_parts = update.callback_query.data.split(" ")

    if len(query_parts) == 1:
        command, values = query_parts, []
    else:
        command, values = query_parts[0], query_parts[1:]

    match command:
        case "best_match":
            await best_match(update, context, values[0])
        case "wait_for":
            await send_wait_for(update, context, values[0])
        case "noop":
            await update.callback_query.answer()
        case _:
            await update.callback_query.answer(t("search.something_went_wrong", get_lang(update)))


# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Communication
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #


async def send_wait_for(update: Update, context: ContextTypes.DEFAULT_TYPE, engine_name: str):
    assert update.callback_query
    L = get_lang(update)
    await update.callback_query.answer(t("search.creating_url", L, engine=engine_name))


async def general_image_search(update: Update, image_url: URL, reply_done: asyncio.Event):
    """Send reverse image search link buttons for the image sent to us."""
    assert update.message
    try:
        chat_config = ChatConfig(update.message.chat_id)

        if not chat_config.show_buttons:
            reply_done.set()
            return

        active_engines = engines
        if chat_config.button_engines is not None:
            active_engines = [e for e in engines if e.name in chat_config.button_engines]

        L = get_lang(update)
        top_buttons = []
        if chat_config.show_best_match:
            top_buttons.append(
                [InlineKeyboardButton(text=t("search.best_match", L), callback_data="best_match " + str(image_url))]
            )
        if chat_config.show_link:
            top_buttons.append([InlineKeyboardButton(text=t("search.go_to_image", L), url=str(image_url))])

        engine_buttons = []

        # Collect PreWorkEngine placeholders and regular buttons
        prework_engines: dict[asyncio.Task, PreWorkEngine] = {}
        for engine in active_engines:
            if isinstance(engine, PreWorkEngine) and (button := engine.empty_button()):
                task = asyncio.create_task(engine(image_url))
                prework_engines[task] = engine
                engine_buttons.append(button)
            elif button := engine(image_url):
                engine_buttons.append(button)

        def _build_markup(eng_buttons):
            rows = list(top_buttons) + list(chunks(eng_buttons, 2))
            return InlineKeyboardMarkup(rows)

        reply = t("search.select_engine", L)
        reply_markup = _build_markup(engine_buttons)
        reply_message: Message = await update.message.reply_text(
            text=reply,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
            reply_to_message_id=update.message.message_id,
        )
        reply_done.set()

        # Update buttons as PreWorkEngines finish
        if prework_engines:
            done, _pending = await asyncio.wait(prework_engines.keys(), timeout=15)
            for task in done:
                engine = prework_engines[task]
                try:
                    updated_button = task.result()
                except Exception:
                    updated_button = None
                for button in engine_buttons[:]:
                    if button.text.endswith(engine.name):
                        if not updated_button:
                            engine_buttons.remove(button)
                        else:
                            engine_buttons[engine_buttons.index(button)] = updated_button
            with contextlib.suppress(TelegramError):
                await reply_message.edit_reply_markup(reply_markup=_build_markup(engine_buttons))
    finally:
        if not reply_done.is_set():
            reply_done.set()


async def best_match(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str | URL,
    general_done: asyncio.Event | None = None,
):
    """Find best matches for an image."""
    if update.callback_query:
        await update.callback_query.answer(show_alert=False)

    user = update.effective_user
    message = update.effective_message
    assert user and message

    L = get_lang(update)
    if user.id not in ADMIN_IDS and (last_time := last_used.get(user.id)) and time() - last_time < 10:
        if general_done:
            await general_done.wait()
        await context.bot.send_message(
            text=t("search.slow_down", L), chat_id=message.chat_id, reply_to_message_id=message.message_id
        )
        return
    last_used[user.id] = time()

    chat_config = ChatConfig(message.chat_id)
    searchable_engines = [engine for engine in engines if engine.best_match_implemented]
    if chat_config.auto_search_engines is not None:
        searchable_engines = [e for e in searchable_engines if e.name in chat_config.auto_search_engines]

    # Event to hold results until "⏳ searching..." is sent
    results_gate = asyncio.Event()

    search_task = asyncio.create_task(
        _best_match_search(update, context, searchable_engines, URL(str(url)), results_gate, L)
    )

    if general_done:
        await general_done.wait()

    search_message = await context.bot.send_message(
        text=t("search.searching", L), chat_id=message.chat_id, reply_to_message_id=message.message_id
    )
    results_gate.set()

    try:
        match_found = await asyncio.wait_for(search_task, timeout=65)
    except TimeoutError:
        match_found = False

    engines_used_html = ", ".join([b(en.name) for en in searchable_engines])
    if not match_found:
        chat_config.failures_in_a_row += 1
        if chat_config.failures_in_a_row > 4 and chat_config.auto_search_enabled:
            chat_config.auto_search_enabled = False
            await message.reply_text(t("search.auto_disable.message", L))
        await search_message.edit_text(
            t("search.no_results", L, engines=engines_used_html),
            ParseMode.HTML,
        )
    else:
        chat_config.failures_in_a_row = 0
        result_text = t("search.results_found", L, engines=engines_used_html)
        if not chat_config.auto_search_enabled:
            result_text += t("search.results_found_reenable", L)
        await search_message.edit_text(
            result_text,
            ParseMode.HTML,
        )


_AUTO_DISABLE_THRESHOLD = 5


def _track_engine_result(chat_id: int, engine_name: str, found: bool) -> bool:
    """Track consecutive empty results per engine. Returns True if the engine was just auto-disabled."""
    chat_config = ChatConfig(chat_id)
    counts = dict(chat_config.engine_empty_counts)

    if found:
        counts.pop(engine_name, None)
        chat_config.engine_empty_counts = counts
        return False

    counts[engine_name] = counts.get(engine_name, 0) + 1
    chat_config.engine_empty_counts = counts

    if counts[engine_name] < _AUTO_DISABLE_THRESHOLD:
        return False

    relevant = [e.name for e in engines if e.best_match_implemented]
    current = list(chat_config.auto_search_engines or relevant)
    if engine_name not in current or len(current) <= 1:
        return False

    current.remove(engine_name)
    chat_config.auto_search_engines = current
    counts[engine_name] = 0
    chat_config.engine_empty_counts = counts
    metrics.engine_auto_disabled_total.labels(engine=engine_name).inc()
    return True


async def _best_match_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    search_engines: list[GenericRISEngine],
    url: URL,
    results_gate: asyncio.Event,
    L: str = "en",
):
    message = update.effective_message
    assert message
    identifiers = []
    thumbnail_identifiers = []
    match_found = False

    metrics.concurrent_searches.inc()
    _reply_to_msg_id: int | None = message.message_id

    engine_start_times: dict[asyncio.Task, float] = {}
    engine_tasks: dict[asyncio.Task, GenericRISEngine] = {}
    for en in search_engines:
        if hasattr(en, "_user_lang"):
            en._user_lang = L  # type: ignore[union-attr]
        task = asyncio.create_task(en.best_match(url))
        engine_tasks[task] = en
        engine_start_times[task] = time()

    try:
        done_tasks: set[asyncio.Task] = set()
        pending = set(engine_tasks.keys())

        while pending:
            done_batch, pending = await asyncio.wait(pending, timeout=60, return_when=asyncio.FIRST_COMPLETED)
            if not done_batch:
                break  # timeout
            done_tasks.update(done_batch)

            for future in done_batch:
                engine = engine_tasks[future]
                duration = time() - engine_start_times[future]
                metrics.search_duration_seconds.labels(provider=engine.name).observe(duration)
                try:
                    logger.debug("%s Searching for %s", engine.name, url)
                    result, meta = future.result()

                    if meta:
                        logger.debug("Found something UmU")
                        metrics.provider_results_total.labels(provider=engine.name, status="hit").inc()
                        _track_engine_result(message.chat_id, engine.name, found=True)

                        button_list = []
                        if more_button := engine(str(url), t("search.more_button", L)):
                            button_list.append(more_button)

                        if buttons := meta.get("buttons"):
                            button_list.extend(buttons)

                        button_list = list(chunks(button_list, 3))

                        identifier = meta.get("identifier")
                        thumbnail_identifier = meta.get("thumbnail_identifier")
                        if identifier in identifiers and thumbnail_identifier not in thumbnail_identifiers:
                            result = {}
                            result[t("search.results.duplicate_result", L)] = ""
                        elif identifier not in identifiers and thumbnail_identifier in thumbnail_identifiers:
                            result[t("search.results.duplicate_thumbnail", L)] = ""
                            del meta["thumbnail"]
                        elif identifier in identifiers and thumbnail_identifier in thumbnail_identifiers:
                            continue

                        await results_gate.wait()

                        reply, media_group = build_reply(result, meta, L)
                        _disable_preview = not meta.get("thumbnail") or bool(media_group)
                        try:
                            provider_msg = await message.reply_html(
                                reply,
                                reply_markup=InlineKeyboardMarkup(button_list),
                                reply_to_message_id=_reply_to_msg_id,
                                disable_web_page_preview=_disable_preview,
                            )
                        except BadRequest as er:
                            if "message to be replied not found" not in er.message.lower():
                                raise
                            _reply_to_msg_id = None
                            provider_msg = await message.reply_html(
                                reply,
                                reply_markup=InlineKeyboardMarkup(button_list),
                                disable_web_page_preview=_disable_preview,
                            )
                        if media_group:
                            try:
                                await message.reply_media_group(
                                    media_group,
                                    reply_to_message_id=provider_msg.message_id,
                                )
                            except BadRequest as er:
                                if "webpage_media_empty" not in er.message:
                                    raise
                        if result:
                            match_found = True
                        if identifier:
                            identifiers.append(identifier)
                        if thumbnail_identifier:
                            thumbnail_identifiers.append(thumbnail_identifier)
                    else:
                        metrics.provider_results_total.labels(provider=engine.name, status="miss").inc()
                        disabled = _track_engine_result(message.chat_id, engine.name, found=False)
                        if disabled:
                            await context.bot.send_message(
                                chat_id=message.chat_id,
                                text=t("search.results.engine_auto_disabled", L, engine=engine.name),
                                parse_mode=ParseMode.HTML,
                            )
                except RateLimitError as rate_err:
                    metrics.provider_rate_limits_total.labels(provider=engine.name).inc()
                    logger.info("Rate limit hit for %s: %s", engine.name, rate_err)

                    await results_gate.wait()
                    more_button = engine(str(url), t("search.more_button", L))
                    button_list = list(chunks([more_button], 3)) if more_button else []
                    period = (
                        f"{rate_err.period} limit"
                        if rate_err.period
                        else t("search.results.rate_limit_default_period", L)
                    )
                    rate_msg = t("search.results.rate_limit", L, engine=b(engine.name), period=period)
                    try:
                        await message.reply_html(
                            rate_msg,
                            reply_markup=InlineKeyboardMarkup(button_list) if button_list else None,
                            reply_to_message_id=_reply_to_msg_id,
                            disable_web_page_preview=True,
                        )
                    except BadRequest as er:
                        if "message to be replied not found" not in er.message.lower():
                            raise
                        _reply_to_msg_id = None
                        await message.reply_html(
                            rate_msg,
                            reply_markup=InlineKeyboardMarkup(button_list) if button_list else None,
                            disable_web_page_preview=True,
                        )
                except EngineError as engine_err:
                    metrics.provider_results_total.labels(provider=engine.name, status="error").inc()
                    logger.exception("Engine error [%s]", engine.name, exc_info=engine_err)
                except Exception as error:
                    metrics.provider_results_total.labels(provider=engine.name, status="error").inc()
                    user = update.effective_user
                    user_info = f"{user.full_name} (tg://user?id={user.id})" if user else "Unknown"
                    logger.error(
                        "Best match error [%s]\nUser: %s\nImage: %s",
                        engine.name,
                        user_info,
                        url,
                        exc_info=error,
                    )
    finally:
        # Cancel any remaining pending tasks
        for task in pending:
            task.cancel()
        metrics.concurrent_searches.dec()

    metrics.search_results_total.labels(has_results=str(match_found).lower()).inc()
    return match_found


# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Misc
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #


def build_reply(result: ResultData, meta: MetaData, L: str = "en") -> tuple[str, list[InputMediaPhoto] | None]:
    provider_link = a(b(meta["provider"]), meta["provider_url"])
    reply = t("search.results.provided_by", L, provider=provider_link)

    if via := meta.get("provided_via"):
        via_text = b(via)
        if via_url := meta.get("provided_via_url"):
            via_text = a(b(via), via_url)
        reply += t("search.results.with_via", L, via=via_text)

    if similarity := meta.get("similarity"):
        reply += t("search.results.with_similarity", L, similarity=str(similarity))

    media_group = []
    if thumbnail := meta.get("thumbnail"):
        if isinstance(thumbnail, URL):
            reply = hidden_a(thumbnail) + reply
        else:
            media_group = [InputMediaPhoto(str(url), filename=Path(str(url)).name) for url in thumbnail]

    reply += "\n\n"

    for key, value in result.items():
        reply += title(html_mod.escape(translate_field(str(key), L)))
        if isinstance(value, set):
            reply += ", ".join(html_mod.escape(str(v)) for v in value)
        elif isinstance(value, list):
            reply += ", ".join(code(html_mod.escape(str(v))) for v in value)
        else:
            reply += code(html_mod.escape(str(value)))
        reply += "\n"

    if media_group:
        return reply, media_group

    return reply, None


async def video_to_url(attachment: Document | Video | Animation | Sticker) -> URL:
    filename = f"{attachment.file_unique_id}.jpg"
    if uploader.file_exists(filename):
        return uploader.get_url(filename)

    if attachment.file_size and attachment.file_size > MAX_TELEGRAM_FILE_SIZE:
        if attachment.thumbnail:
            return await image_to_url(attachment.thumbnail)
        raise ValueError(t("search.files.video_too_large"))

    video_file = await attachment.get_file()
    with NamedTemporaryFile(suffix=".mp4") as tmp:
        await video_file.download_to_drive(tmp.name)
        loop = asyncio.get_running_loop()
        frame_bytes = await loop.run_in_executor(_process_executor, _extract_video_frame, tmp.name)

    with io.BytesIO(frame_bytes) as file:
        return upload_file(file, filename)


_JPEG_ALIASES = {"jfif", "jpe", "jpeg"}


async def image_to_url(attachment: PhotoSize | Sticker | Document) -> URL:
    if isinstance(attachment, Document):
        extension = (attachment.file_name or "unknown.jpg").lower().rsplit(".", 1)[1].strip(".")
        if extension in _JPEG_ALIASES:
            extension = "jpg"
    else:
        extension = "jpg" if isinstance(attachment, PhotoSize) else "png"

    filename = f"{attachment.file_unique_id}.{extension}"
    if uploader.file_exists(filename):
        return uploader.get_url(filename)

    photo_file = await attachment.get_file()
    with io.BytesIO() as file:
        await photo_file.download_to_memory(file)
        if extension != "jpg":
            file.seek(0)
            with Image.open(file) as image:
                file.seek(0)
                image.save(file, extension)
        return upload_file(file, filename)
