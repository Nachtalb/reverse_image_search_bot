from __future__ import annotations

import asyncio
import contextlib
import html as html_mod
from logging import getLogger
from pathlib import Path
from time import time

from telegram import (
    Animation,
    Document,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
    PhotoSize,
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
from reverse_image_search_bot.i18n import lang as get_lang
from reverse_image_search_bot.i18n import t, translate_field
from reverse_image_search_bot.settings import ADMIN_IDS
from reverse_image_search_bot.utils import chunks
from reverse_image_search_bot.utils.tags import a, b, code, hidden_a, title

from .utils import (
    _detect_file_type,
    _normalize_extension,
    image_to_url,
    last_used,
    video_to_url,
)

logger = getLogger("BEST MATCH")


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

    file_type = _detect_file_type(attachment)
    file_ext = _normalize_extension(attachment)

    metrics.files_received_total.labels(file_type=file_type).inc()
    metrics.files_by_extension_total.labels(extension=file_ext).inc()
    file_size = getattr(attachment, "file_size", None)
    if file_size:
        metrics.file_size_bytes.labels(file_type=file_type).observe(float(file_size))

    # Count query received (private chats only — groups counted in group_file_handler)
    chat_type = update.effective_chat.type or "unknown"
    if chat_type == "private":
        metrics.queries_received_total.labels(chat_type=chat_type, file_type=file_type).inc()

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
        metrics.queries_handled_total.labels(chat_type=chat_type, file_type=file_type, language=language).inc()

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
