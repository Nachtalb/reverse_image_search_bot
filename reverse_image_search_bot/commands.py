import io
from logging import getLogger
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image
from moviepy.video.io.VideoFileClip import VideoFileClip
from telegram import ChatAction, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram import Animation, Document, PhotoSize, Sticker, Video
from telegram.ext import CallbackContext
from telegram.parsemode import ParseMode
from yarl import URL

from reverse_image_search_bot.engines import engines
from reverse_image_search_bot.engines.generic import GenericRISEngine
from reverse_image_search_bot.uploaders import uploader
from reverse_image_search_bot.utils import chunks, upload_file


logger = getLogger("BEST MATCH")


def start(update: Update, context: CallbackContext):
    """Send Start / Help message to client."""
    reply = Path(__file__).with_name("start.md").read_text()
    update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)

    image = Path(__file__).parent / "images/example_usage.png"

    context.bot.send_photo(
        update.message.chat_id,
        photo=io.BytesIO(image.read_bytes()),  # For some reason it didn't want to accept the path itself ¯\_(ツ)_/¯
        caption="Example Usage",
    )


def image_search(update: Update, context: CallbackContext):
    if not update.message:
        return
    message = update.message.reply_text("...")
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
                image_url = image_to_url(attachment)
            case _:
                message.edit_text("Format is not supported")
                return

        general_image_search(update, image_url)
    except Exception:
        message.edit_text("An error occurred please contact the @Nachtalb for help.")
        raise
    message.delete()


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

    button_list.extend(chunks([en(image_url) for en in engines], 2))

    reply = f"Use **Best Match** to directly find the best match from here withing telegram.[​]({image_url})"
    reply_markup = InlineKeyboardMarkup(button_list)
    update.message.reply_text(
        text=reply,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN,
    )


def callback_best_match(update: Update, context: CallbackContext):
    """Find best matches for an image for a :class:`telegram.callbackquery.CallbackQuery`."""
    context.bot.answer_callback_query(update.callback_query.id, show_alert=False)
    url = update.callback_query.data.split(" ")[1]
    best_match(update, context, url)


def best_match(update: Update, context: CallbackContext, url: str | URL):
    """Find best matches for an image."""
    message = update.callback_query.message
    message = context.bot.send_message(
        text="Searching...", chat_id=message.chat_id, reply_to_message_id=message.message_id
    )

    match_found = False
    for engine in engines:
        if type(engine) is GenericRISEngine:
            continue

        logger.info("Searching %s for %s", engine.name, url)
        try:
            match, buttons = engine.best_match(url)
            if match:
                logger.info("Found something UmU")
                button_list = [engine(url=str(url), text="More")]
                button_list.extend(buttons)
                button_list = list(chunks(button_list, 3))

                message.reply_html(build_reply(match), reply_markup=InlineKeyboardMarkup(button_list))
                match_found = True
        except Exception as error:
            logger.error("Engine failure: %s", engine)
            logger.exception(error)

    if not match_found:
        message.edit_text("Searching... No results")
    else:
        message.delete()


def build_reply(match: dict) -> str:
    md = [f'<b>Provider: {match["provider"]}</b>']

    if thumbnail := match.get("thumbnail"):
        md.append(f'<a href="{thumbnail}">​</a>')

    for key, value in match.items():
        if key not in ["thumbnail", "provider"]:
            if isinstance(value, (str, URL)) and URL(value).scheme.startswith("http"):
                md.append(f"<b>{key}</b>: {value}")
            else:
                md.append(f"<b>{key}</b>: <code>{value}</code>")
    return "\n".join(md)
