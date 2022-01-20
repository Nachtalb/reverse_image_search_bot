from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import json
from logging import getLogger
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, Thread
from time import time
from typing import Callable

from PIL import Image
from emoji import emojize
from moviepy.video.io.VideoFileClip import VideoFileClip
from telegram import (
    ChatAction,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    User,
)
from telegram import Animation, Document, Message, PhotoSize, Sticker, Video
from telegram.ext import CallbackContext
from telegram.parsemode import ParseMode
from yarl import URL

from reverse_image_search_bot.engines import engines
from reverse_image_search_bot.engines.generic import GenericRISEngine, PreWorkEngine
from reverse_image_search_bot.engines.types import MetaData, ResultData
from reverse_image_search_bot.settings import ADMIN_IDS
from reverse_image_search_bot.uploaders import uploader
from reverse_image_search_bot.utils import ReturnableThread, chunks, upload_file
from reverse_image_search_bot.utils.tags import a, b, code, hidden_a, pre, title


logger = getLogger("BEST MATCH")
last_used: dict[int, float] = {}


# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Commands
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #


def id_command(update: Update, context: CallbackContext):
    if update.effective_chat:
        update.message.reply_html(pre(json.dumps(update.effective_chat.to_dict(), sort_keys=True, indent=4)))


def send_template_command(name: str) -> Callable:
    local = Path(__file__).parent
    reply_file = local / f"texts/{name}.md"
    image_file = local / f"images/{name}.jpg"

    def wrapper(update, context):
        return _send_template_command(update, context, reply_file, image_file)

    return wrapper


def _send_template_command(update: Update, context: CallbackContext, reply_file: Path, image_file: Path):
    reply = reply_file.read_text()
    if len(reply) > 1000:
        update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)
        reply = None

    if image_file.is_file():
        with image_file.open("br") as image_obj:
            update.message.reply_photo(image_obj, caption=reply, parse_mode=ParseMode.MARKDOWN)


tips_command = send_template_command("tips")
help_command = send_template_command("help")


def more_command(update: Update, context: CallbackContext):
    context.args = ["more"]
    engines_command(update, context)


def engines_command(update: Update, context: CallbackContext):
    reply = ""
    if not context.args:
        reply = "To get even more info use /more.\n\n"

    for engine in engines:
        parts = [title(engine.name) + str(engine.provider_url)]
        if context.args:
            parts.append(title("Description") + engine.description)
        if engine.recommendation:
            parts.append(title("Recommended for") + "\n- " + "\n- ".join(engine.recommendation))
        if engine.types:
            parts.append(title("Used for") + ", ".join(engine.types))

        parts.append(title("Supports inline search") + ("✅" if engine.best_match_implemented else "❌"))

        reply += "\n".join(parts) + "\n\n"

    update.message.reply_html(reply, reply_to_message_id=update.message.message_id, disable_web_page_preview=True)


def file_handler(update: Update, context: CallbackContext):
    if not update.message:
        return
    message = update.message.reply_text("⌛ Give me a sec...")
    context.bot.send_chat_action(chat_id=update.message.chat_id, action=ChatAction.TYPING)

    attachment = update.message.effective_attachment
    if isinstance(attachment, list):
        attachment = attachment[-1]

    try:
        match attachment:
            case i if (isinstance(i, Document) and i.mime_type.startswith("video")) or isinstance(
                i, (Video, Animation)
            ):
                image_url = video_to_url(attachment)
            case PhotoSize() | Sticker():
                if isinstance(attachment, Sticker) and attachment.is_animated:
                    message.edit_text("Animated stickers are not supported.")
                    return
                image_url = image_to_url(attachment)
            case _:
                message.edit_text("Format is not supported")
                return

        lock = Lock()
        lock.acquire()
        Thread(target=general_image_search, args=(update, image_url, lock)).start()
        best_match(update, context, image_url, lock)
    except Exception as error:
        message.edit_text("An error occurred please contact the @Nachtalb for help.")
        try:
            image_url  # type: ignore
        except NameError:
            image_url = None

        error_to_admin(update, context, f"Error: {error}", image_url, attachment)  # type: ignore
        raise
    message.delete()


def callback_query_handler(update: Update, context: CallbackContext):
    data = update.callback_query.data.split(" ")

    if len(data) == 1:
        command, values = data, []
    else:
        command, values = data[0], data[1:]

    match command:
        case "best_match":
            best_match(update, context, values[0])
        case "wait_for":
            send_wait_for(update, context, values[0])
        case _:
            update.callback_query.answer("Something went wrong")


# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Communication
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #


def send_wait_for(update: Update, context: CallbackContext, engine_name: str):
    update.callback_query.answer(f"Creating {engine_name} search url...")


def general_image_search(update: Update, image_url: URL, lock: Lock):
    """Send a reverse image search link for the image sent to us"""
    try:
        default_buttons = [
            [InlineKeyboardButton(text="Best Match", callback_data="best_match " + str(image_url))],
            [InlineKeyboardButton(text="Go To Image", url=str(image_url))],
        ]
        buttons = []

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {}

            for engine in engines:
                if isinstance(engine, PreWorkEngine) and (button := engine.empty_button()):
                    futures[executor.submit(engine, image_url)] = engine
                    buttons.append(button)
                elif button := engine(image_url):
                    buttons.append(button)

            button_list = list(chunks(buttons, 2))

            reply = "Use /engines to get a overview of supprted engines and what they are good at."
            reply_markup = InlineKeyboardMarkup(default_buttons + button_list)
            message: Message = update.message.reply_text(
                text=reply,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=update.message.message_id,
            )
            lock.release()

            for future in as_completed(futures):
                engine = futures[future]
                new_button = future.result()
                for button in buttons[:]:
                    if button.text.endswith(engine.name):
                        if not new_button:
                            buttons.remove(button)
                        else:
                            buttons[buttons.index(button)] = new_button
                message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(default_buttons + list(chunks(buttons, 2))))
    finally:
        if lock.locked:
            try:
                lock.release()
            except RuntimeError:
                pass


def best_match(update: Update, context: CallbackContext, url: str | URL, lock: Lock = None):
    """Find best matches for an image."""
    if update.callback_query:
        update.callback_query.answer(show_alert=False)

    user: User = update.effective_user  # type: ignore
    message: Message = update.effective_message  # type: ignore

    if user.id not in ADMIN_IDS and (last_time := last_used.get(user.id)) and time() - last_time < 10:
        if lock:
            wait_for(lock)
        context.bot.send_message(
            text="Slow down a bit please....", chat_id=message.chat_id, reply_to_message_id=message.message_id
        )
        return
    else:
        last_used[user.id] = time()

    searchable_engines = [engine for engine in engines if engine.best_match_implemented]

    best_match_lock = Lock()
    best_match_lock.acquire()
    try:
        thread = ReturnableThread(_best_match_search, args=(update, context, searchable_engines, url, best_match_lock))
        thread.start()

        if lock:
            wait_for(lock)
            # We only have to wait for the other thread to release the lock, we don't need it any further than that

        search_message = context.bot.send_message(
            text="⏳ searching...", chat_id=message.chat_id, reply_to_message_id=message.message_id
        )
    finally:
        best_match_lock.release()

    match_found = thread.join()

    engines_used_html = ", ".join([b(en.name) for en in searchable_engines])
    if not match_found:
        search_message.edit_text(
            emojize(
                f":red_circle: I searched for you on {engines_used_html} but didn't find anything. Please try another"
                " engine above and take a look at /tips."
            ),
            ParseMode.HTML,
        )
    else:
        search_message.edit_text(
            emojize(
                f":blue_circle: I searched for you on {engines_used_html}. You can try others above for more results"
            ),
            ParseMode.HTML,
        )


def _best_match_search(update: Update, context: CallbackContext, engines: list[GenericRISEngine], url: URL, lock: Lock):
    message: Message = update.effective_message  # type: ignore
    identifiers = []
    thumbnail_identifiers = []
    match_found = False

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(en.best_match, url): en for en in engines}
        for future in as_completed(futures):
            engine = futures[future]
            try:
                logger.debug("%s Searching for %s", engine.name, url)
                result, meta = future.result()

                if meta:
                    logger.debug("Found something UmU")

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
                        result["Dplicate thumbnail omitted"] = ""
                        del meta["thumbnail"]
                    elif identifier in identifiers and thumbnail_identifier in thumbnail_identifiers:
                        continue

                    wait_for(lock)

                    message.reply_html(
                        text=build_reply(result, meta),
                        reply_markup=InlineKeyboardMarkup(button_list),
                        reply_to_message_id=message.message_id,
                        disable_web_page_preview="errors" in meta,
                    )
                    if "errors" not in meta and result:
                        match_found = True
                    if identifier:
                        identifiers.append(identifier)
                    if thumbnail_identifier:
                        thumbnail_identifiers.append(thumbnail_identifier)
            except Exception as error:
                error_to_admin(update, context, message=f"Best match error: {error}", image_url=url)
                logger.error("Engine failure: %s", engine)
                logger.exception(error)

    return match_found


# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Misc
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #


def build_reply(result: ResultData, meta: MetaData) -> str:
    reply = f"Provided by: {a(b(meta['provider']), meta['provider_url'])}"  # type: ignore

    if via := meta.get("provided_via"):
        via = b(via)
        if via_url := meta.get("provided_via_url"):
            via = a(b(via), via_url)
        reply += f" with {via}"

    if similarity := meta.get("similarity"):
        reply += f" with {b(str(similarity) + '%')} similarity"

    if thumbnail := meta.get("thumbnail"):
        reply = hidden_a(thumbnail) + reply

    reply += "\n\n"

    for key, value in result.items():
        if isinstance(value, str) and value.startswith("#"):  # Tags
            reply += title(key) + value + "\n"
        else:
            reply += title(key) + code(value) + "\n"

    if errors := meta.get("errors"):
        for error in errors:
            reply += error

    return reply


def video_to_url(attachment: Document | Video) -> URL:
    filename = f"{attachment.file_unique_id}.jpg"
    if uploader.file_exists(filename):
        return uploader.get_url(filename)

    if attachment.file_size > 2e7:  # Bots are only allowed to download up to 20MB
        return image_to_url(attachment.thumb)

    video = attachment.get_file()
    with NamedTemporaryFile() as video_file:
        video.download(out=video_file)
        with VideoFileClip(video_file.name, audio=False) as video_clip:
            frame = video_clip.get_frame(0)

    with io.BytesIO() as file:
        Image.fromarray(frame, "RGB").save(file, "jpeg")
        file.seek(0)
        return upload_file(file, filename)


def image_to_url(attachment: PhotoSize | Sticker) -> URL:
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


def error_to_admin(update: Update, context: CallbackContext, message: str, image_url: str | URL, attachment=None):
    try:
        user = update.effective_user
        message += f"\nUser: {user.mention_html()}"  # type: ignore
        buttons = None
        if image_url:
            buttons = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Best Match", callback_data=f"best_match {image_url}")]]
            )

        if not attachment:
            message += f"\nImage: {image_url}"
            for admin in ADMIN_IDS:
                context.bot.send_message(admin, message, ParseMode.HTML, reply_markup=buttons)
            return

        send_method = getattr(
            context.bot,
            "send_%s" % (attachment.__class__.__name__.lower() if not isinstance(attachment, PhotoSize) else "photo"),
        )
        if user and send_method and user.id != 713276361:
            for admin in ADMIN_IDS:
                if isinstance(attachment, Sticker):
                    send_method(admin, attachment)
                    context.bot.send_message(admin, message, parse_mode=ParseMode.HTML, reply_markup=buttons)
                else:
                    send_method(admin, attachment, caption=message, parse_mode=ParseMode.HTML, reply_markup=buttons)
    except Exception as error:
        logger.exception(error)
