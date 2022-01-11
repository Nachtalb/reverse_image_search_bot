import io
import os
from tempfile import NamedTemporaryFile
from uuid import uuid4

from PIL import Image
from moviepy.video.io.VideoFileClip import VideoFileClip
from telegram import Bot, ChatAction, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.parsemode import ParseMode

from reverse_image_search_bot.utils import dict_to_str
from .image_search import BingReverseImageSearchEngine, \
    GoogleReverseImageSearchEngine, IQDBReverseImageSearchEngine, \
    TinEyeReverseImageSearchEngine, YandexReverseImageSearchEngine, \
    SauceNaoReverseImageSearchEngine, TraceReverseImageSearchEngine


def start(bot: Bot, update: Update):
    """Send Start / Help message to client.

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
    """
    reply = """*Reverse Image Search Bot*

*How to use me*
Send me an image, sticker, video/gif or url and I will send you direct reverse image search links for SauceNao, Google, Yandex and the like.
For anime images I recommend SauceNao, for other images I recommend to use Google, Yandex.

Supported engines:
- General: Goolge, Yandex, Bing & TinEye
- Artworks & Anime: SauceNAO, IQDB, Trace & ascii2d

Inline search results:
- IQDB unlimited
- Trace 1000/month
- TineEye 50/day 150/week
- SauceNAO 6/30s 200/24h

*Commands*
- /help, /start: show this help message

*Author*
https://github.com/Nachtalb

*Donations*
- [PayPal](https://paypal.me/Espig)
- BTC: `3E6Pw8gwLJSyfumpjuJ6CWNKjZJLCmXZ2G`
- BTC/BSC: `0x3c5211340Db470A31F1a37E343E326db69FF2F5C`
- ETH: `0x3c5211340Db470A31F1a37E343E326db69FF2F5C`
- USDC: `0x3c5211340Db470A31F1a37E343E326db69FF2F5C`
- PayString: `nachtalb$paystring.crypto.com`


*Other Bots*
- @XenianBot All general purpose but with tons of functionality


*Issues / Contributions*
- Code repository: https://github.com/Nachtalb/reverse\\_image\\_search\\_bot
- @Nachtalb
- via /support at @XenianBot

Thank you for using @reverse\\_image\\_search\\_bot.
"""

    update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)

    current_dir = os.path.dirname(os.path.realpath(__file__))
    image_dir = os.path.join(current_dir, 'images/example_usage.png')
    bot.send_photo(update.message.chat_id, photo=open(image_dir, 'rb'), caption='Example Usage')


def group_image_reply_search(bot: Bot, update: Update):
    """Reverse search for reply mentions to images in groups

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
    """
    print(update.message.reply_to_message.document.file_id)
    pass


def gif_image_search(bot: Bot, update: Update):
    """Send a reverse image search link for the GIF sent to us

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
    """
    update.message.reply_text('Please wait for your results ...')
    bot.send_chat_action(chat_id=update.message.chat_id, action=ChatAction.TYPING)

    document = update.message.document or update.message.video
    video = bot.getFile(document.file_id)

    with NamedTemporaryFile() as video_file:
        video.download(out=video_file)
        video_clip = VideoFileClip(video_file.name, audio=False)

        with NamedTemporaryFile(suffix='.jpg') as jpg_file:
            video_clip.save_frame(jpg_file.name)
            general_image_search(bot, update, jpg_file, 'jpg')


def sticker_image_search(bot: Bot, update: Update):
    """Send a reverse image search link for the image of the sticker sent to us

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
    """
    update.message.reply_text('Please wait for your results ...')
    bot.send_chat_action(chat_id=update.message.chat_id, action=ChatAction.TYPING)

    sticker_image = bot.getFile(update.message.sticker.file_id)
    converted_image = io.BytesIO()

    with io.BytesIO() as image_buffer:
        sticker_image.download(out=image_buffer)
        with io.BufferedReader(image_buffer) as image_file:
            pil_image = Image.open(image_file).convert("RGBA")
            pil_image.save(converted_image, 'png')

            general_image_search(bot, update, converted_image, 'png')


def image_search_link(bot: Bot, update: Update):
    """Send a reverse image search link for the image he sent us to the client

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
    """
    update.message.reply_text('Please wait for your results ...')
    bot.send_chat_action(chat_id=update.message.chat_id, action=ChatAction.TYPING)

    photo = bot.getFile(update.message.photo[-1].file_id)
    with io.BytesIO() as image_buffer:
        photo.download(out=image_buffer)
        with io.BufferedReader(image_buffer) as image_file:
            general_image_search(bot, update, image_file)


def general_image_search(bot: Bot, update: Update, image_file, image_extension: str=None):
    """Send a reverse image search link for the image sent to us

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
        image_file: File like image to search for
        image_extension (:obj:`str`): What extension the image should have. Default is 'jpg'
    """
    image_extension = image_extension or 'jpg'

    iqdb_search = IQDBReverseImageSearchEngine()
    google_search = GoogleReverseImageSearchEngine()
    tineye_search = TinEyeReverseImageSearchEngine()
    bing_search = BingReverseImageSearchEngine()
    yandex_search = YandexReverseImageSearchEngine()
    saucenao_search = SauceNaoReverseImageSearchEngine()
    trace_search = TraceReverseImageSearchEngine()

    image_url = iqdb_search.upload_image(image_file, image_name + '.' + image_extension)

    button_list = [[
        InlineKeyboardButton(text='Best Match (TinyEye & IQDB)', callback_data='best_match ' + image_url)
    ], [
        InlineKeyboardButton(text='Go To Image', url=image_url)
    ], [
        saucenao_search.button(image_url),
        google_search.button(image_url),
    ], [
        iqdb_search.button(image_url),
        yandex_search.button(image_url),
    ], [
        bing_search.button(image_url),
        tineye_search.button(image_url),
    ], [
        trace_search.button(image_url),
    ]]

    reply = 'You can either use "Best Match" to get your best match right here or search for yourself.'
    reply_markup = InlineKeyboardMarkup(button_list)
    update.message.reply_text(
        text=reply,
        reply_markup=reply_markup
    )


def callback_best_match(bot: Bot, update: Update):
    """Find best matches for an image for a :class:`telegram.callbackquery.CallbackQuery`.

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
    """
    bot.answer_callback_query(update.callback_query.id, show_alert=False)
    url = update.callback_query.data.split(' ')[1]
    best_match(bot, update, [url, ])


def best_match(bot: Bot, update: Update, args: list):
    """Find best matches for an image.

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
        args (:obj:`list`): List of arguments passed by the user
    """
    if not args:
        update.message.reply_text('You have to give me an URL to make this work.')
        return
    tineye = TinEyeReverseImageSearchEngine()
    iqdb = IQDBReverseImageSearchEngine()
    tineye.search_url = args[0]
    iqdb.search_url = args[0]

    chat_id = update.effective_chat.id
    message = bot.send_message(chat_id, 'Searching on <b>TinEye</b>, IQDB..', parse_mode=ParseMode.HTML)

    match = tineye.best_match
    if not match:
        bot.edit_message_text(
            text='Searching on TinEye, <b>IQDB</b>....',
            chat_id=chat_id,
            message_id=message.message_id,
            parse_mode=ParseMode.HTML
        )
        match = iqdb.best_match

    if match:
        reply = (
            'Best Match:\n'
            'Link: [{website_name}]({website})\n'.format(
                website_name=match['website_name'],
                website=match['website'],
            )
        )
        reply += dict_to_str(match, ignore=['website_name', 'website', 'image_url', 'thumbnail'])

        image_url = match.get('image_url', None) or match.get('website', None)
        thumbnail = match.get('image_url', None) or match.get('thumbnail', None)

        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(text='Open', url=image_url), ], ])
        bot.delete_message(chat_id, message.message_id)

        bot.send_photo(chat_id=chat_id, photo=thumbnail)
        bot.send_message(
            chat_id=chat_id,
            text=reply,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        bot.edit_message_text(
            text='Searching on TinEye, IQDB.... yielded no results',
            chat_id=chat_id,
            message_id=message.message_id,
            parse_mode=ParseMode.MARKDOWN
        )


def unknown(bot: Bot, update: Update):
    """Send a error message to the client if the entered command did not work.

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
    """
    update.message.reply_text("Sorry, I didn't understand that command.")
