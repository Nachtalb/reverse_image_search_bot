import logging

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

import os
import sys
from threading import Thread

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, Filters, MessageHandler, Updater, CallbackContext

from . import settings
from .commands import callback_best_match, start, image_search



def error(update: Update, context: CallbackContext):
    """Log all errors from the telegram bot api

    Args:
        update (:obj:`telegram.update.Update`): Telegram update
        context (:obj:`telegram.ext.CallbackContext`): Bot context
    """
    logger.exception(context.error)
    logger.warning('Error caused by this update: %s' % (update))


def main():
    updater = Updater(settings.TELEGRAM_API_TOKEN)
    dispatcher = updater.dispatcher

    def stop_and_restart():
        """Gracefully stop the Updater and replace the current process with a new one."""
        updater.stop()
        os.execl(sys.executable, sys.executable, *sys.argv)

    def restart(update: Update, context: CallbackContext):
        """Start the restarting process

        Args:
            update (:obj:`telegram.update.Update`): Telegram update
            context (:obj:`telegram.ext.CallbackContext`): Bot context
        """
        update.message.reply_text('Bot is restarting...')
        logger.info('Gracefully restarting...')
        Thread(target=stop_and_restart).start()

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", start))
    dispatcher.add_handler(CommandHandler('restart', restart, filters=Filters.user(username='@Nachtalb')))
    dispatcher.add_handler(CallbackQueryHandler(callback_best_match))

    dispatcher.add_handler(MessageHandler(Filters.sticker | Filters.photo | Filters.video | Filters.document, image_search))

    # log all errors
    dispatcher.add_error_handler(error)

    updater.start_polling()
    logger.info('Started bot. Waiting for requests...')
    updater.idle()


if __name__ == '__main__':
    main()
