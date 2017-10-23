import io
import os

from botanio import botan
from .settings import BOTAN_API_TOKEN
from PIL import Image
from telegram import Bot, ChatAction, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.parsemode import ParseMode

from .image_search import BingReverseImageSearchEngine, GoogleReverseImageSearchEngine, IQDBReverseImageSearchEngine, \
    TinEyeReverseImageSearchEngine


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

*Features*
- Give you image reverse search links
- Supports IQDB, Google, TinEye and Bing
- Supports normal images like JPG, PNG, WEBP
- Supports stickers
- Best Match information by IQDB

*ToDo*
- Support for GIFs
- Best Match information by TinEye

*Commands*
- /help, /start: show a help message with information about the bot and it's usage.

*Attention whore stuff* 
Please share this bot with your friends so that I ([the magician](https://github.com/Nachtalb/) behind this project) 
have enough motivation to continue and maintain this bot.

Check out my other project\[s\]: 
- [@insta_looter_bot](https://github.com/Nachtalb/insta_looter_bot) - Download images and videos from Instagram via 
Telegram


*Contributions*
_Bug report / Feature request_
If you have found a bug or want a new feature, please make an issue here: [Nachtalb/animu_image_search_bot](https://github.com/Nachtalb/animu_image_search_bot)

_Code Contribution / Pull Requests_
Please use a line length of 120 characters and [Google Style Python Docstrings](http://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html). 

Thank you for using [@anime_image_search_bot](https://t.me/anime_image_search_bot).
"""

    update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)

    current_dir = os.path.dirname(os.path.realpath(__file__))
    image_dir = os.path.join(current_dir, 'images/example_usage.png')
    bot.send_photo(update.message.chat_id, photo=open(image_dir, 'rb'), caption='Example Usage')


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
            pil_image = Image.open(image_file).convert("RGB")
            pil_image.save(converted_image, 'jpeg')

            general_image_search(bot, update, converted_image)


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


def general_image_search(bot: Bot, update: Update, image_file):
    """Send a reverse image search link for the image sent to us

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
        image_file: File like image to search for
    """
    iqdb_search = IQDBReverseImageSearchEngine()
    google_search = GoogleReverseImageSearchEngine()
    tineye_search = TinEyeReverseImageSearchEngine()
    bing_search = BingReverseImageSearchEngine()

    image_url = iqdb_search.upload_image(image_file)

    iqdb_url = iqdb_search.get_search_link_by_url(image_url)
    google_url = google_search.get_search_link_by_url(image_url)
    tineye_url = tineye_search.get_search_link_by_url(image_url)
    bing_url = bing_search.get_search_link_by_url(image_url)

    best_match = iqdb_search.best_match
    reply = ''
    button_list = []
    if best_match:
        reply += ('Best Match:\n'
                  'Link: [{website_name}]({website})\n'
                  'Similarity: {similarity}%\n'
                  'Size: {width}x{height}px').format(
            website_name=best_match['website_name'],
            website=best_match['website'],
            similarity=best_match['similarity'],
            width=best_match['size']['width'],
            height=best_match['size']['height']
        )
        button_list = [
            [InlineKeyboardButton(text='Best Match', url=best_match['website'])],
        ]
        bot.send_photo(chat_id=update.message.chat_id, photo=best_match['thumbnail'])
    else:
        reply = 'You can search for the image on the following site:'
    button_list.append([
        InlineKeyboardButton(text='IQDB', url=iqdb_url),
        InlineKeyboardButton(text='GOOGLE', url=google_url),
    ])
    button_list.append([
        InlineKeyboardButton(text='TINEYE', url=tineye_url),
        InlineKeyboardButton(text='BING', url=bing_url),
    ])

    reply_markup = InlineKeyboardMarkup(button_list)
    update.message.reply_text(
        text=reply,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )


def unknown(bot: Bot, update: Update):
    """Send a error message to the client if the entered command did not work.

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
    """
    print(botan.track(BOTAN_API_TOKEN, update.message.from_user, update.message.to_dict(), 'unknown'))
    update.message.reply_text("Sorry, I didn't understand that command.")
