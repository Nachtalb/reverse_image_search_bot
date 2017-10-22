import io

from telegram import Bot, ChatAction, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.parsemode import ParseMode

from .image_search import GoogleReverseImageSearchEngine, IQDBReverseImageSearchEngine


def start(bot: Bot, update: Update):
    """Send Start / Help message to client.

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
    """
    update.message.reply_text('Send me an image to search for it on iqdb or google.')


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
            iqdb_search = IQDBReverseImageSearchEngine()
            google_search = GoogleReverseImageSearchEngine()
            image_url = iqdb_search.upload_image(image_file)
            iqdb_url = iqdb_search.get_search_link_by_url(image_url)
            google_url = google_search.get_search_link_by_url(image_url)

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
    button_list.append([
        InlineKeyboardButton(text='IQDB', url=iqdb_url),
        InlineKeyboardButton(text='GOOGLE', url=google_url)
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
    update.message.reply_text("Sorry, I didn't understand that command.")
