import io
import os
from tempfile import NamedTemporaryFile
from uuid import uuid4

from PIL import Image
from botanio import botan
from moviepy.video.io.VideoFileClip import VideoFileClip
from telegram import Bot, ChatAction, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.parsemode import ParseMode

from reverse_image_search_bot.utils import dict_to_str
from .image_search import BingReverseImageSearchEngine, GoogleReverseImageSearchEngine, IQDBReverseImageSearchEngine, \
    TinEyeReverseImageSearchEngine
from .settings import BOTAN_API_TOKEN


def start(bot: Bot, update: Update):
    """Send Start / Help message to client.

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
    """
    print(botan.track(BOTAN_API_TOKEN, update.message.from_user.id, update.message.to_dict(), '/start'))

    reply = """*Anime Image Search Bot*

[@anime_image_search_bot](https://t.me/anime_image_search_bot)

*How to use me*
Send me images or stickers and I will send you direct reverse image search links for IQDB, Google, TinEye and Bing. 
For anime images I recommend IQDB and TinEye, for other images I recommend to use Google or TinEye.

Attention: The best match feature sometimes does not find a best match on TinEye, even though you do when you open the 
link. Why is this? This is because TinEye I reached the limit of TinEye's free service. TinEye provides 50 searches per 
day to a max of 150 searches per week. And I will not pay for the TinEye atm because it is way too expensive for me.

*Features*
- Give you image reverse search links
- Supports IQDB, Google, TinEye and Bing
- Supports normal images like JPG, PNG, WEBP
- Supports stickers
- Supports GIFs (can take some time till the GIFs are ready)
- Supports Videos (will be searched as GIFs)
- Best Match information by TinEye
- Best Match information by IQDB as fallback

*Commands*
- /help, /start: show a help message with information about the bot and it's usage.
- /best\_match URL: Search for the best match on TinEye (and IQDB when nothing is found on TinEye). The `URL` is a link 
    to an image

*Attention whore stuff* 
Please share this bot with your friends so that I ([the magician](https://github.com/Nachtalb/) behind this project) 
have enough motivation to continue and maintain this bot.

Check out my other project\[s\]: 
- [@insta_looter_bot](https://github.com/Nachtalb/insta_looter_bot) - Download images and videos from Instagram via 
Telegram


*Contributions*
_Bug report / Feature request_
If you have found a bug or want a new feature, please make an issue here: [Nachtalb/reverse_image_search_bot](https://github.com/Nachtalb/reverse_image_search_bot)

_Code Contribution / Pull Requests_
Please use a line length of 120 characters and [Google Style Python Docstrings](http://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html). 

Thank you for using [@anime_image_search_bot](https://t.me/anime_image_search_bot).
"""

    update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)

    current_dir = os.path.dirname(os.path.realpath(__file__))
    image_dir = os.path.join(current_dir, 'images/example_usage.png')
    bot.send_photo(update.message.chat_id, photo=open(image_dir, 'rb'), caption='Example Usage')


def gif_image_search(bot: Bot, update: Update):
    """Send a reverse image search link for the GIF sent to us

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
    """
    print(botan.track(BOTAN_API_TOKEN, update.message.from_user.id, update.message.to_dict(), '/gif_image_search'))

    update.message.reply_text('Please wait for your results ...')
    bot.send_chat_action(chat_id=update.message.chat_id, action=ChatAction.TYPING)

    document = update.message.document or update.message.video
    video = bot.getFile(document.file_id)

    with NamedTemporaryFile() as video_file:
        video.download(out=video_file)
        video_clip = VideoFileClip(video_file.name, audio=False)

        with NamedTemporaryFile(suffix='.gif') as gif_file:
            video_clip.write_gif(gif_file.name)

            dirname = os.path.dirname(gif_file.name)
            file_name = os.path.splitext(gif_file.name)[0]
            compressed_gif_path = os.path.join(dirname, file_name + '-min.gif')

            os.system('gifsicle -O3 --lossy=50 -o {dst} {src}'.format(dst=compressed_gif_path, src=gif_file.name))
            if os.path.isfile(compressed_gif_path):
                general_image_search(bot, update, compressed_gif_path, 'gif')
            else:
                general_image_search(bot, update, gif_file.name, 'gif')


def sticker_image_search(bot: Bot, update: Update):
    """Send a reverse image search link for the image of the sticker sent to us

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
    """
    print(botan.track(BOTAN_API_TOKEN, update.message.from_user.id, update.message.to_dict(), '/sticker_image_search'))

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
    print(botan.track(BOTAN_API_TOKEN, update.message.from_user.id, update.message.to_dict(), '/image_search_link'))

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

    image_url = iqdb_search.upload_image(image_file, 'irs-' + str(uuid4())[:8] + '.' + image_extension)

    iqdb_url = iqdb_search.get_search_link_by_url(image_url)
    google_url = google_search.get_search_link_by_url(image_url)
    tineye_url = tineye_search.get_search_link_by_url(image_url)
    bing_url = bing_search.get_search_link_by_url(image_url)

    button_list = [[
        InlineKeyboardButton(text='Best Match', callback_data='best_match ' + image_url)
    ], [
        InlineKeyboardButton(text='Go To Image', url=image_url)
    ], [
        InlineKeyboardButton(text='IQDB', url=iqdb_url),
        InlineKeyboardButton(text='GOOGLE', url=google_url),
    ], [
        InlineKeyboardButton(text='TINEYE', url=tineye_url),
        InlineKeyboardButton(text='BING', url=bing_url),
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
    print(botan.track(BOTAN_API_TOKEN, update.effective_user.id, update.callback_query.to_dict(), '/callback_best_match'))

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
    if update.message:
        print(botan.track(BOTAN_API_TOKEN, update.message.from_user.id, update.message.to_dict(), '/best_match'))

    if not args:
        update.message.reply_text('You have to give me an URL to make this work.')
        return
    tineye = TinEyeReverseImageSearchEngine()
    iqdb = IQDBReverseImageSearchEngine()
    tineye.search_url = args[0]
    iqdb.search_url = args[0]

    chat_id = update.effective_chat.id
    message = bot.send_message(chat_id, 'Searching for best match on TinEye...')

    match = tineye.best_match
    if not match:
        bot.edit_message_text(
            text='Nothing found on TinEye, searching on IQDB...',
            chat_id=chat_id,
            message_id=message.message_id
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
            text='Nothing found on TinEye nor IQDB.',
            chat_id=chat_id,
            message_id=message.message_id,
        )


def unknown(bot: Bot, update: Update):
    """Send a error message to the client if the entered command did not work.

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
    """
    print(botan.track(BOTAN_API_TOKEN, update.message.from_user, update.message.to_dict(), 'unknown'))
    update.message.reply_text("Sorry, I didn't understand that command.")
