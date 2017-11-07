import logging
import os
import sys
from threading import Thread

from telegram import Bot, TelegramError, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, Filters, MessageHandler, Updater

from . import settings
from .commands import best_match, callback_best_match, image_search_link, start, sticker_image_search, unknown

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def error(bot: Bot, update: Update, error: TelegramError):
    """Log all errors from the telegram bot api

    Args:
        bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
        update (:obj:`telegram.update.Update`): Telegram Api Update Object
        error (:obj:`telegram.error.TelegramError`): Telegram Api TelegramError Object
    """
    logger.warning('Update "%s" caused error "%s"' % (update, error))


def main():
    updater = Updater(settings.TELEGRAM_API_TOKEN)
    dispatcher = updater.dispatcher

    def stop_and_restart():
        """Gracefully stop the Updater and replace the current process with a new one."""
        updater.stop()
        os.execl(sys.executable, sys.executable, *sys.argv)

    def restart(bot: Bot, update: Update):
        """Start the restarting process

        Args:
            bot (:obj:`telegram.bot.Bot`): Telegram Api Bot Object.
            update (:obj:`telegram.update.Update`): Telegram Api Update Object
        """
        update.message.reply_text('Bot is restarting...')
        logger.info('Gracefully restarting...')
        Thread(target=stop_and_restart).start()

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", start))
    dispatcher.add_handler(CommandHandler('restart', restart, filters=Filters.user(username='@Nachtalb')))
    dispatcher.add_handler(CommandHandler('best_match', best_match, pass_args=True))
    dispatcher.add_handler(CallbackQueryHandler(callback_best_match))

    dispatcher.add_handler(MessageHandler(Filters.sticker, sticker_image_search))
    dispatcher.add_handler(MessageHandler(Filters.photo, image_search_link))
    dispatcher.add_handler(MessageHandler(Filters.command, unknown))

    # log all errors
    dispatcher.add_error_handler(error)

    updater.start_polling()
    logger.info('Started bot. Waiting for requests...')
    updater.idle()


if __name__ == '__main__':
    main()
