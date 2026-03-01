import contextlib
import io
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from logging import getLogger
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, Thread
from time import time

from emoji import emojize
from moviepy.video.io.VideoFileClip import VideoFileClip
from PIL import Image
from telegram import (
    Animation,
    ChatAction,
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
    User,
    Video,
)
from telegram.error import BadRequest
from telegram.ext import CallbackContext
from telegram.parsemode import ParseMode
from yarl import URL

from reverse_image_search_bot import metrics
from reverse_image_search_bot.config import ChatConfig, UserConfig
from reverse_image_search_bot.engines import engines
from reverse_image_search_bot.engines.generic import GenericRISEngine, PreWorkEngine
from reverse_image_search_bot.engines.types import MetaData, ResultData
from reverse_image_search_bot.settings import ADMIN_IDS
from reverse_image_search_bot.uploaders import uploader
from reverse_image_search_bot.utils import ReturnableThread, chunks, upload_file
from reverse_image_search_bot.utils.tags import a, b, code, hidden_a, pre, title

logger = getLogger("BEST MATCH")
last_used: dict[int, float] = {}

# Telegram Bot API file download limit (20 MB)
MAX_TELEGRAM_FILE_SIZE = 20 * 1024 * 1024


# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Commands
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #


def id_command(update: Update, context: CallbackContext):
    metrics.commands_total.labels(command="id").inc()
    if update.effective_chat:
        update.message.reply_html(pre(json.dumps(update.effective_chat.to_dict(), sort_keys=True, indent=4)))


# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Settings (per-chat inline keyboard UI)
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #


def _is_settings_allowed(update: Update, context: CallbackContext) -> bool:
    """Allow settings changes in private chats always; in groups only for admins."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False
    if chat.type == "private":
        return True
    try:
        member = context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("creator", "administrator")
    except Exception:
        return False


def _settings_main_text(chat_config: ChatConfig) -> str:
    return "⚙️ <b>Chat Settings</b>\nConfigure how the bot behaves in this chat."


def _settings_main_keyboard(chat_config: ChatConfig) -> InlineKeyboardMarkup:
    auto = "✅" if chat_config.auto_search_enabled else "❌"
    buttons = "✅" if chat_config.show_buttons else "❌"
    as_engines_label = "🔍 Auto-search engines →" if chat_config.auto_search_enabled else "🔍 Auto-search engines 🔒"
    as_engines_cb = (
        "settings:menu:auto_search_engines"
        if chat_config.auto_search_enabled
        else "settings:disabled:auto_search_engines"
    )
    btn_engines_label = "🔘 Engine buttons →" if chat_config.show_buttons else "🔘 Engine buttons 🔒"
    btn_engines_cb = "settings:menu:button_engines" if chat_config.show_buttons else "settings:disabled:button_engines"

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"🔍 Auto-search: {auto}", callback_data="settings:toggle:auto_search")],
            [InlineKeyboardButton(f"🔘 Show buttons: {buttons}", callback_data="settings:toggle:show_buttons")],
            [InlineKeyboardButton(as_engines_label, callback_data=as_engines_cb)],
            [InlineKeyboardButton(btn_engines_label, callback_data=btn_engines_cb)],
        ]
    )


def _settings_engines_keyboard(chat_config: ChatConfig, menu: str) -> InlineKeyboardMarkup:
    """Build a per-engine toggle keyboard for either 'auto_search_engines' or 'button_engines'."""
    rows = []

    if menu == "auto_search_engines":
        enabled = chat_config.auto_search_engines  # None = all enabled
        cb_prefix = "settings:toggle:auto_search_engine"
        # Only show engines that support best_match for autosearch
        relevant = [e for e in engines if e.best_match_implemented]
    else:
        enabled = chat_config.button_engines  # None = all enabled
        cb_prefix = "settings:toggle:button_engine"
        relevant = list(engines)
        # Mirror the final button layout: Best Match alone, Link alone, then engines in pairs
        bm = "✅" if chat_config.show_best_match else "❌"
        link = "✅" if chat_config.show_link else "❌"
        rows.append([InlineKeyboardButton(f"{bm} Best Match", callback_data="settings:toggle:show_best_match")])
        rows.append([InlineKeyboardButton(f"{link} 🔗 Go To Image", callback_data="settings:toggle:show_link")])

    engine_btns = [
        InlineKeyboardButton(
            f"{'✅' if (enabled is None or e.name in enabled) else '❌'} {e.name}",
            callback_data=f"{cb_prefix}:{e.name}",
        )
        for e in relevant
    ]
    rows.extend(chunks(engine_btns, 2))
    rows.append([InlineKeyboardButton("← Back", callback_data="settings:back")])
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


def settings_command(update: Update, context: CallbackContext):
    metrics.commands_total.labels(command="settings").inc()
    chat_config = ChatConfig(update.effective_chat.id)  # type: ignore
    if _is_group(update.effective_chat.id) and not chat_config.onboarded:
        chat_config.onboarded = True  # opening settings counts as onboarding
    update.message.reply_html(
        _settings_main_text(chat_config),
        reply_markup=_settings_main_keyboard(chat_config),
    )


def settings_callback_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data  # e.g. "settings:toggle:auto_search"

    # Noop / disabled buttons
    if data == "settings:noop":
        query.answer()
        return
    if data.startswith("settings:disabled:"):
        reason = {
            "auto_search_engines": "Enable auto-search first to configure its engines.",
            "button_engines": 'Enable "Show buttons" first to configure engine buttons.',
        }.get(data.split(":", 2)[2], "Enable the master toggle first.")
        query.answer(reason, show_alert=False)
        return

    if not _is_settings_allowed(update, context):
        query.answer("Only group admins can change settings.", show_alert=True)
        return

    chat_config = ChatConfig(update.effective_chat.id)  # type: ignore
    parts = data.split(":", 2)  # ["settings", action, value]
    action = parts[1] if len(parts) > 1 else ""
    value = parts[2] if len(parts) > 2 else ""

    is_group = _is_group(update.effective_chat.id)

    if action == "toggle":
        if value == "auto_search":
            if not is_group and chat_config.auto_search_enabled and not chat_config.show_buttons:
                query.answer("⚠️ Enable engine buttons first — at least one must be active.", show_alert=True)
                return
            chat_config.auto_search_enabled = not chat_config.auto_search_enabled
        elif value == "show_buttons":
            if not is_group and chat_config.show_buttons and not chat_config.auto_search_enabled:
                query.answer("⚠️ Enable auto-search first — at least one must be active.", show_alert=True)
                return
            chat_config.show_buttons = not chat_config.show_buttons
        elif value == "show_best_match":
            if chat_config.show_best_match and _button_count(chat_config) <= 1:
                query.answer("⚠️ At least one button must stay enabled.", show_alert=True)
                return
            chat_config.show_best_match = not chat_config.show_best_match
            action = "disabled" if not chat_config.show_best_match else "enabled"
            metrics.button_toggle_total.labels(button="best_match", action=action).inc()
        elif value == "show_link":
            if chat_config.show_link and _button_count(chat_config) <= 1:
                query.answer("⚠️ At least one button must stay enabled.", show_alert=True)
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
                    query.answer("⚠️ At least one engine must stay enabled.", show_alert=True)
                    return
                current.remove(engine_name)
                metrics.engine_manual_toggle_total.labels(
                    engine=engine_name, menu="auto_search", action="disabled"
                ).inc()
            else:
                current.append(engine_name)
                chat_config.reset_engine_counter(engine_name)  # fresh start after manual re-enable
                metrics.engine_manual_toggle_total.labels(
                    engine=engine_name, menu="auto_search", action="enabled"
                ).inc()
            # If all enabled, store None (= all)
            chat_config.auto_search_engines = None if set(current) >= set(relevant) else current
        elif value.startswith("button_engine:"):
            engine_name = value[len("button_engine:") :]
            all_names = [e.name for e in engines]
            current = chat_config.button_engines
            if current is None:
                current = all_names[:]
            if engine_name in current:
                if _button_count(chat_config, excluding_engine=engine_name) < 1:
                    query.answer("⚠️ At least one button must stay enabled.", show_alert=True)
                    return
                current.remove(engine_name)
                metrics.engine_manual_toggle_total.labels(engine=engine_name, menu="button", action="disabled").inc()
            else:
                current.append(engine_name)
                metrics.engine_manual_toggle_total.labels(engine=engine_name, menu="button", action="enabled").inc()
            chat_config.button_engines = None if set(current) >= set(all_names) else current

        # Re-render appropriate menu
        if value.startswith("auto_search_engine:"):
            with contextlib.suppress(Exception):
                query.edit_message_reply_markup(
                    reply_markup=_settings_engines_keyboard(chat_config, "auto_search_engines")
                )
        elif value.startswith("button_engine:") or value in ("show_link", "show_best_match"):
            with contextlib.suppress(Exception):
                query.edit_message_reply_markup(reply_markup=_settings_engines_keyboard(chat_config, "button_engines"))
        else:
            with contextlib.suppress(Exception):
                query.edit_message_reply_markup(reply_markup=_settings_main_keyboard(chat_config))

    elif action == "menu":
        with contextlib.suppress(Exception):
            query.edit_message_reply_markup(reply_markup=_settings_engines_keyboard(chat_config, value))

    elif action == "back":
        with contextlib.suppress(Exception):
            query.edit_message_text(
                _settings_main_text(chat_config),
                parse_mode="HTML",
                reply_markup=_settings_main_keyboard(chat_config),
            )

    query.answer()


_LOCAL = Path(__file__).parent
_HELP_TEXT = _LOCAL / "texts/help.html"
_HELP_IMAGE = _LOCAL / "images/help.jpg"


def start_command(update: Update, context: CallbackContext):
    metrics.commands_total.labels(command="start").inc()
    chat = update.effective_chat
    if chat and chat.type != "private":
        chat_config = ChatConfig(chat.id)
        if not chat_config.onboarded:
            _send_onboarding(update, context)
            return
        update.message.reply_text(
            "🔎 Send me an image, sticker, or video and I'll find its source.\n\n/search · /settings",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    else:
        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton("/help"), KeyboardButton("/settings")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        update.message.reply_text(
            "🔎 Send me an image, sticker, or video and I'll find its source.",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


def on_added_to_group(update: Update, context: CallbackContext):
    """Send start message when bot is added to a group."""
    message = update.message
    if not message or not message.new_chat_members:
        return
    for member in message.new_chat_members:
        if member.id == context.bot.id:
            _send_onboarding(update, context)
            break


def _send_onboarding(update: Update, context: CallbackContext):
    """Send the group onboarding prompt with preset choices."""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔍 Search results only", callback_data="onboard:search_only")],
            [InlineKeyboardButton("🔍 Full (results + buttons)", callback_data="onboard:full")],
            [InlineKeyboardButton("❌ Manual only (/search)", callback_data="onboard:manual")],
            [InlineKeyboardButton("⚙️ Open settings", callback_data="onboard:settings")],
        ]
    )
    text = (
        "👋 <b>How should I handle images in this group?</b>\n\n"
        "• <b>Search results only</b> — auto-search images, show results\n"
        "• <b>Full</b> — auto-search + show engine buttons\n"
        "• <b>Manual</b> — only search when someone replies with /search\n"
        "• <b>Settings</b> — configure everything yourself"
    )
    (update.effective_message or update.message).reply_html(text, reply_markup=keyboard)


def _is_group(chat_id: int) -> bool:
    return chat_id < 0


def onboard_callback_handler(update: Update, context: CallbackContext):
    """Handle onboarding button presses."""
    query = update.callback_query
    choice = query.data.split(":", 1)[1]
    chat_id = update.effective_chat.id

    if not _is_settings_allowed(update, context):
        query.answer("Only group admins can configure the bot.", show_alert=True)
        return

    chat_config = ChatConfig(chat_id)
    chat_config.onboarded = True

    if choice == "search_only":
        chat_config.auto_search_enabled = True
        chat_config.show_buttons = False
        query.edit_message_text(
            "✅ Set to <b>search results only</b>. Change anytime with /settings.",
            parse_mode=ParseMode.HTML,
        )
    elif choice == "full":
        chat_config.auto_search_enabled = True
        chat_config.show_buttons = True
        query.edit_message_text(
            "✅ Set to <b>full mode</b> (results + buttons). Change anytime with /settings.",
            parse_mode=ParseMode.HTML,
        )
    elif choice == "manual":
        chat_config.auto_search_enabled = False
        chat_config.show_buttons = False
        query.edit_message_text(
            "✅ Set to <b>manual mode</b>. Use /search to search. Change anytime with /settings.",
            parse_mode=ParseMode.HTML,
        )
    elif choice == "settings":
        query.edit_message_text("⚙️ Opening settings...")
        update.effective_message.reply_html(
            _settings_main_text(chat_config),
            reply_markup=_settings_main_keyboard(chat_config),
        )

    query.answer()


def group_file_handler(update: Update, context: CallbackContext):
    """Handle images in group chats — onboard first if needed."""
    chat_id = update.effective_chat.id
    chat_config = ChatConfig(chat_id)

    if not chat_config.onboarded:
        _send_onboarding(update, context)
        return

    if not chat_config.auto_search_enabled and not chat_config.show_buttons:
        # Manual mode — ignore direct images, user must use /search
        return

    file_handler(update, context)


def help_command(update: Update, context: CallbackContext):
    metrics.commands_total.labels(command="help").inc()
    with _HELP_IMAGE.open("rb") as photo:
        update.message.reply_photo(
            photo,
            caption=_HELP_TEXT.read_text(),
            parse_mode=ParseMode.HTML,
            api_kwargs={"show_caption_above_media": True},
        )


def search_command(update: Update, context: CallbackContext):
    metrics.commands_total.labels(command="search").inc()
    orig_message: Message | None = update.message.reply_to_message
    if not orig_message:
        update.message.reply_text("When using /search you have to reply to a message with an image or video")
        return

    file_handler(update, context, orig_message)


def file_handler(update: Update, context: CallbackContext, message: Message = None):
    message = message or update.effective_message
    if not message:
        return

    user = message.from_user
    if user.id in context.bot._banned_users:
        message.reply_text("🔴 You are banned from using this bot due to uploading illegal content.")
        return

    context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)

    attachment = message.effective_attachment
    if isinstance(attachment, list):
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
    if hasattr(attachment, "file_size") and attachment.file_size:
        metrics.file_size_bytes.labels(file_type=file_type).observe(attachment.file_size)

    language = getattr(user, "language_code", None) or "unknown"

    try:
        image_url = None
        error = None
        try:
            if (
                (isinstance(attachment, Document) and attachment.mime_type.startswith("video"))
                or isinstance(attachment, (Video, Animation))
                or (isinstance(attachment, Sticker) and attachment.is_video)
            ):
                search_type = "video_frame" if isinstance(attachment, Video) else file_type
                image_url = video_to_url(attachment)  # type: ignore
            elif (
                isinstance(attachment, Document) and attachment.mime_type.endswith(("jpeg", "png", "webp"))
            ) or isinstance(attachment, (PhotoSize, Sticker)):
                if isinstance(attachment, Sticker) and attachment.is_animated:
                    message.reply_text("Animated stickers are not supported.")
                    return
                search_type = file_type
                image_url = image_to_url(attachment)
        except ValueError as e:
            message.reply_text(str(e))
            return
        except Exception as e:
            error = e

        if not image_url:
            message.reply_text("Format is not supported")
            if error is not None:
                raise error
            return

        # Track usage metrics
        metrics.searches_total.labels(type=search_type, language=language).inc()
        metrics.searches_by_user_total.labels(user_id=str(user.id)).inc()

        general_search_lock = Lock()
        general_search_lock.acquire()
        Thread(target=general_image_search, args=(update, image_url, general_search_lock)).start()
        config = UserConfig(update.effective_user)  # type: ignore
        chat_config = ChatConfig(update.effective_chat.id)  # type: ignore
        if config.auto_search_enabled and chat_config.auto_search_enabled:
            best_match(update, context, image_url, general_search_lock)
    except Exception as error:
        message.reply_text("An error occurred, try again.")
        raise


def callback_query_handler(update: Update, context: CallbackContext):
    query_parts = update.callback_query.data.split(" ")

    if len(query_parts) == 1:
        command, values = query_parts, []
    else:
        command, values = query_parts[0], query_parts[1:]

    match command:
        case "best_match":
            best_match(update, context, values[0])
        case "wait_for":
            send_wait_for(update, context, values[0])
        case "noop":
            update.callback_query.answer()
        case _:
            update.callback_query.answer("Something went wrong")


# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Communication
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #


def send_wait_for(update: Update, context: CallbackContext, engine_name: str):
    update.callback_query.answer(f"Creating {engine_name} search url...")


def general_image_search(update: Update, image_url: URL, reply_sent_lock: Lock):
    """Send a reverse image search link for the image sent to us"""
    try:
        chat_config = ChatConfig(update.message.chat_id)

        if not chat_config.show_buttons:
            reply_sent_lock.release()
            return

        active_engines = engines
        if chat_config.button_engines is not None:
            active_engines = [e for e in engines if e.name in chat_config.button_engines]

        top_buttons = []
        if chat_config.show_best_match:
            top_buttons.append([InlineKeyboardButton(text="Best Match", callback_data="best_match " + str(image_url))])
        if chat_config.show_link:
            top_buttons.append([InlineKeyboardButton(text="🔗 Go To Image", url=str(image_url))])

        engine_buttons = []

        with ThreadPoolExecutor(max_workers=5) as executor:
            prework_futures = {}

            for engine in active_engines:
                if isinstance(engine, PreWorkEngine) and (button := engine.empty_button()):
                    prework_futures[executor.submit(engine, image_url)] = engine
                    engine_buttons.append(button)
                elif button := engine(image_url):
                    engine_buttons.append(button)

            def _build_markup(eng_buttons):
                rows = list(top_buttons) + list(chunks(eng_buttons, 2))
                return InlineKeyboardMarkup(rows)

            reply = "Select a search engine:"
            reply_markup = _build_markup(engine_buttons)
            reply_message: Message = update.message.reply_text(
                text=reply,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=update.message.message_id,
            )
            reply_sent_lock.release()

            try:
                for future in as_completed(prework_futures, timeout=15):
                    engine = prework_futures[future]
                    updated_button = future.result()
                    for button in engine_buttons[:]:
                        if button.text.endswith(engine.name):
                            if not updated_button:
                                engine_buttons.remove(button)
                            else:
                                engine_buttons[engine_buttons.index(button)] = updated_button
                    reply_message.edit_reply_markup(reply_markup=_build_markup(engine_buttons))
            except FuturesTimeoutError:
                pass
    finally:
        if reply_sent_lock.locked:
            with contextlib.suppress(RuntimeError):
                reply_sent_lock.release()


def best_match(update: Update, context: CallbackContext, url: str | URL, general_search_lock: Lock | None = None):
    """Find best matches for an image."""
    if update.callback_query:
        update.callback_query.answer(show_alert=False)

    user: User = update.effective_user  # type: ignore
    message: Message = update.effective_message  # type: ignore
    config = UserConfig(user)

    if user.id not in ADMIN_IDS and (last_time := config.last_auto_search) and time() - last_time < 10:
        if general_search_lock:
            wait_for(general_search_lock)
        context.bot.send_message(
            text="Slow down a bit please....", chat_id=message.chat_id, reply_to_message_id=message.message_id
        )
        return
    config.used_auto_search()

    chat_config = ChatConfig(message.chat_id)
    searchable_engines = [engine for engine in engines if engine.best_match_implemented]
    if chat_config.auto_search_engines is not None:
        searchable_engines = [e for e in searchable_engines if e.name in chat_config.auto_search_engines]

    # Held until "⏳ searching..." is sent — prevents results arriving before the status message
    results_gate = Lock()
    results_gate.acquire()
    try:
        search_thread = ReturnableThread(
            _best_match_search, args=(update, context, searchable_engines, url, results_gate)
        )
        search_thread.start()

        if general_search_lock:
            # Wait for general_image_search to send its buttons message before we send "⏳ searching..."
            wait_for(general_search_lock)

        search_message = context.bot.send_message(
            text="⏳ searching...", chat_id=message.chat_id, reply_to_message_id=message.message_id
        )
    finally:
        results_gate.release()

    match_found = search_thread.join(timeout=65)

    engines_used_html = ", ".join([b(en.name) for en in searchable_engines])
    if not match_found:
        config.failures_in_a_row += 1
        if config.failures_in_a_row > 4 and config.auto_search_enabled:
            config.auto_search_enabled = False
            update.message.reply_text(
                emojize(
                    ":yellow_circle: You had 5 searches in a row returning no results thus I disabled auto search for"
                    " you. This helps to prevent hitting rate limits of the search engines making the bot more useful"
                    " for everyone. At the moment the auto search compatible engines are for anime & manga related"
                    " content. If you mainly search for other material please keep auto search disabled. You can use"
                    " /settings to reenable it."
                )
            )
        search_message.edit_text(
            emojize(
                f":red_circle: I searched for you on {engines_used_html} but didn't find anything. Please try another"
                " engine above."
            ),
            ParseMode.HTML,
        )
    else:
        config.failures_in_a_row = 0
        search_message.edit_text(
            emojize(
                f":blue_circle: I searched for you on {engines_used_html}. You can try others above for more results."
            )
            + (" You may reenable auto-search via /settings if you want." if not config.auto_search_enabled else ""),
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

    # Threshold hit — disable if there's at least one other engine still active
    relevant = [e.name for e in engines if e.best_match_implemented]
    current = list(chat_config.auto_search_engines or relevant)
    if engine_name not in current or len(current) <= 1:
        return False  # already disabled or last engine — don't disable

    current.remove(engine_name)
    chat_config.auto_search_engines = current
    counts[engine_name] = 0  # reset so it doesn't re-trigger if re-enabled
    chat_config.engine_empty_counts = counts
    metrics.engine_auto_disabled_total.labels(engine=engine_name).inc()
    return True


def _best_match_search(
    update: Update, context: CallbackContext, engines: list[GenericRISEngine], url: URL, results_gate: Lock
):
    message: Message = update.effective_message  # type: ignore
    identifiers = []
    thumbnail_identifiers = []
    match_found = False

    metrics.concurrent_searches.inc()
    engine_executor = ThreadPoolExecutor(max_workers=5)
    engine_start_times = {}
    engine_futures = {}
    for en in engines:
        future = engine_executor.submit(en.best_match, url)
        engine_futures[future] = en
        engine_start_times[future] = time()
    try:
        for future in as_completed(engine_futures, timeout=60):
            engine = engine_futures[future]
            duration = time() - engine_start_times[future]
            metrics.search_duration_seconds.labels(provider=engine.name).observe(duration)
            try:
                logger.debug("%s Searching for %s", engine.name, url)
                result, meta = future.result()

                if meta:
                    logger.debug("Found something UmU")
                    metrics.provider_results_total.labels(provider=engine.name, status="hit").inc()
                    # Success — reset empty counter for this engine
                    _track_engine_result(message.chat_id, engine.name, found=True)

                    button_list = []
                    more_button = engine(str(url), "More")
                    if more_button := engine(str(url), "More"):
                        button_list.append(more_button)

                    if buttons := meta.get("buttons"):
                        button_list.extend(buttons)

                    button_list = list(chunks(button_list, 3))

                    identifier = meta.get("identifier")
                    thumbnail_identifier = meta.get("thumbnail_identifier")
                    if identifier in identifiers and thumbnail_identifier not in thumbnail_identifiers:
                        result = {}
                        result["Duplicate search result omitted"] = ""
                    elif identifier not in identifiers and thumbnail_identifier in thumbnail_identifiers:
                        result["Duplicate thumbnail omitted"] = ""
                        del meta["thumbnail"]
                    elif identifier in identifiers and thumbnail_identifier in thumbnail_identifiers:
                        continue

                    wait_for(results_gate)

                    reply, media_group = build_reply(result, meta)
                    provider_msg = message.reply_html(
                        reply,
                        reply_markup=InlineKeyboardMarkup(button_list),
                        reply_to_message_id=message.message_id,
                        disable_web_page_preview=not meta.get("thumbnail") or bool(media_group) or "errors" in meta,
                    )
                    if media_group:
                        try:
                            message.reply_media_group(
                                media_group,  # type: ignore
                                reply_to_message_id=provider_msg.message_id,
                            )
                        except BadRequest as er:
                            if "webpage_media_empty" not in er.message:
                                raise
                    if "errors" not in meta and result:
                        match_found = True
                    if identifier:
                        identifiers.append(identifier)
                    if thumbnail_identifier:
                        thumbnail_identifiers.append(thumbnail_identifier)
                else:
                    metrics.provider_results_total.labels(provider=engine.name, status="miss").inc()
                    # Empty result — track and potentially auto-disable
                    disabled = _track_engine_result(message.chat_id, engine.name, found=False)
                    if disabled:
                        context.bot.send_message(
                            chat_id=message.chat_id,
                            text=(
                                f"🔕 <b>{engine.name}</b> was automatically disabled for this chat after "
                                f"5 consecutive empty results. Use /settings to re-enable it."
                            ),
                            parse_mode=ParseMode.HTML,
                        )
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
    except FuturesTimeoutError:
        pass
    finally:
        engine_executor.shutdown(wait=False, cancel_futures=True)
        metrics.concurrent_searches.dec()

    metrics.search_results_total.labels(has_results=str(match_found).lower()).inc()
    return match_found


# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Misc
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #


def build_reply(result: ResultData, meta: MetaData) -> tuple[str, list[InputMediaPhoto] | None]:
    reply = f"Provided by: {a(b(meta['provider']), meta['provider_url'])}"

    if via := meta.get("provided_via"):
        via = b(via)
        if via_url := meta.get("provided_via_url"):
            via = a(b(via), via_url)
        reply += f" with {via}"

    if similarity := meta.get("similarity"):
        reply += f" with {b(str(similarity) + '%')} similarity"

    media_group = []
    if thumbnail := meta.get("thumbnail"):
        if isinstance(thumbnail, URL):
            reply = hidden_a(thumbnail) + reply
        else:
            media_group = [InputMediaPhoto(str(url), filename=Path(str(url)).name) for url in thumbnail]

    reply += "\n\n"

    for key, value in result.items():
        reply += title(key)
        if isinstance(value, set):  # Tags
            reply += ", ".join(value)
        elif isinstance(value, list):
            reply += ", ".join(map(code, value))
        else:
            reply += code(value)
        reply += "\n"

    if errors := meta.get("errors"):
        for error in errors:
            reply += error

    if media_group:
        return reply, media_group

    return reply, None


def video_to_url(attachment: Document | Video | Sticker) -> URL:
    filename = f"{attachment.file_unique_id}.jpg"
    if uploader.file_exists(filename):
        return uploader.get_url(filename)

    if attachment.file_size and attachment.file_size > MAX_TELEGRAM_FILE_SIZE:
        if attachment.thumb:
            return image_to_url(attachment.thumb)
        raise ValueError("This video is too large to download and has no thumbnail. Please send a smaller file.")

    video = attachment.get_file()
    with NamedTemporaryFile() as video_file:
        video.download(out=video_file)
        with VideoFileClip(video_file.name, audio=False) as video_clip:
            frame = video_clip.get_frame(0)

    with io.BytesIO() as file:
        Image.fromarray(frame, "RGB").save(file, "jpeg")
        file.seek(0)
        return upload_file(file, filename)


def image_to_url(attachment: PhotoSize | Sticker | Document) -> URL:
    if isinstance(attachment, Document):
        extension = attachment.file_name.lower().rsplit(".", 1)[1].strip(".")
    else:
        extension = "jpg" if isinstance(attachment, PhotoSize) else "png"

    filename = f"{attachment.file_unique_id}.{extension}"
    if uploader.file_exists(filename):
        return uploader.get_url(filename)

    photo = attachment.get_file()
    with io.BytesIO() as file:
        photo.download(out=file)
        if extension != "jpg":
            file.seek(0)
            with Image.open(file) as image:
                file.seek(0)
                image.save(file, extension)
        return upload_file(file, filename)


def wait_for(lock: Lock):
    if lock and lock.locked:
        lock.acquire()
        lock.release()
