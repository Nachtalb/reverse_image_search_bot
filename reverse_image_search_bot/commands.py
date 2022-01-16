import io
import json
from logging import getLogger
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image
from moviepy.video.io.VideoFileClip import VideoFileClip
from telegram import ChatAction, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram import Animation, Document, Message, PhotoSize, Sticker, Video
from telegram.ext import CallbackContext
from telegram.parsemode import ParseMode
from yarl import URL

from reverse_image_search_bot.engines import engines
from reverse_image_search_bot.engines.types import MetaData, ResultData
from reverse_image_search_bot.settings import ADMIN_IDS
from reverse_image_search_bot.uploaders import uploader
from reverse_image_search_bot.utils import chunks, upload_file


logger = getLogger("BEST MATCH")


def show_id(update: Update, context: CallbackContext):
    if update.effective_chat:
        update.message.reply_html(
            "<pre>%s</pre>" % json.dumps(update.effective_chat.to_dict(), sort_keys=True, indent=4)
        )


def start(update: Update, context: CallbackContext):
    """Send Start / Help message to client."""
    reply = Path(__file__).with_name("start.md").read_text()
    update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)

    file = Path(__file__).parent / "images/example.mp4"

    with file.open("br") as ffile:
        context.bot.send_animation(chat_id=update.message.chat_id, animation=ffile, caption="Example Usage")


def engines_command(update: Update, context: CallbackContext):
    reply = 'To get a desciption of the engines use "/engines more".\n\n'
    engine_template = """<b>{engine.name}</b>: {engine.provider_url}
<b>Recommended for:</b> {recommends}
<b>Used for:</b> {used_for}
{desciption}
"""
    for engine in engines:
        recommends = ", ".join(engine.recommendation) if engine.recommendation else "-"
        used_for = ", ".join(engine.types)
        desciption = f"\n{engine.description}\n" if context.args else ""
        reply += engine_template.format(
            engine=engine,
            recommends=recommends,
            used_for=used_for,
            desciption=desciption,
        )

    update.message.reply_html(reply, reply_to_message_id=update.message.message_id, disable_web_page_preview=True)


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
            message += "\nImage: {image_url}"
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


def image_search(update: Update, context: CallbackContext):
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
                    message.edit_text('Animated stickers are not supported.')
                    return
                image_url = image_to_url(attachment)
            case _:
                message.edit_text("Format is not supported")
                return

        general_image_search(update, image_url)
    except Exception as error:
        message.edit_text("An error occurred please contact the @Nachtalb for help.")
        try:
            image_url  # type: ignore
        except NameError:
            image_url = None

        error_to_admin(update, context, f"Error: {error}", image_url, attachment)  # type: ignore
        raise
    message.delete()
    best_match(update, context, image_url)


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


def general_image_search(update: Update, image_url: URL):
    """Send a reverse image search link for the image sent to us"""
    button_list = [
        [InlineKeyboardButton(text="Best Match", callback_data="best_match " + str(image_url))],
        [InlineKeyboardButton(text="Go To Image", url=str(image_url))],
    ]

    buttons = filter(None, map(lambda en: en(image_url), engines))
    button_list.extend(chunks(list(buttons), 2))

    reply = "Use /engines to get a overview of supprted engines and what they are good at."
    reply_markup = InlineKeyboardMarkup(button_list)
    update.message.reply_text(
        text=reply,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN,
        reply_to_message_id=update.message.message_id,
    )


def callback_best_match(update: Update, context: CallbackContext):
    """Find best matches for an image for a :class:`telegram.callbackquery.CallbackQuery`."""
    context.bot.answer_callback_query(update.callback_query.id, show_alert=False)
    url = update.callback_query.data.split(" ")[1]
    best_match(update, context, url)


def best_match(update: Update, context: CallbackContext, url: str | URL):
    """Find best matches for an image."""
    message: Message = update.effective_message  # type: ignore
    search_message = context.bot.send_message(
        text="⏳ searching...", chat_id=message.chat_id, reply_to_message_id=message.message_id
    )

    identifiers = []
    thumbnail_identifiers = []
    engines_used = []

    match_found = False
    for engine in engines:
        try:
            try:
                logger.debug("%s Searching for %s", engine.name, url)
                result, meta = engine.best_match(url)
            except NotImplementedError:
                logger.debug("%s Has no search implemented", engine.name)
                continue

            engines_used.append(engine.name)
            search_message.edit_text(f"⏳ *{engine.name}*", parse_mode=ParseMode.MARKDOWN)
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

    engines_used_html = ", ".join([f"<b>{name}</b>" for name in engines_used])
    if not match_found:
        search_message.edit_text(
            f"🔴 I searched for you on {engines_used_html} but didn't find anything. Please try another engine above.",
            parse_mode=ParseMode.HTML,
        )
    else:
        search_message.delete()
        context.bot.send_message(
            text=f"🔵 I searched for you on {engines_used_html}. You can try others above for more results",
            parse_mode=ParseMode.HTML,
            chat_id=message.chat_id,
        )


def build_reply(result: ResultData, meta: MetaData) -> str:
    reply = f'Provided by: <b><a href="{meta["provider_url"]}">{meta["provider"]}</a></b>'  # type: ignore

    if via := meta.get("provided_via"):
        via = f"<b>{via}</b>"
        if via_url := meta.get("provided_via_url"):
            via = f'<a href="{via_url}">{via}</a>'
        reply += f" with {via}"

    if similarity := meta.get("similarity"):
        reply += f" with <b>{similarity}%</b> similarity"

    if thumbnail := meta.get("thumbnail"):
        reply = f'<a href="{thumbnail}">​</a>' + reply

    reply += "\n\n"

    for key, value in result.items():
        if isinstance(value, str) and value.startswith("#"):  # Tags
            reply += f"<b>{key}</b>: {value}\n"
        else:
            reply += f"<b>{key}</b>: <code>{value}</code>\n"

    if errors := meta.get("errors"):
        for error in errors:
            reply += error

    return reply
