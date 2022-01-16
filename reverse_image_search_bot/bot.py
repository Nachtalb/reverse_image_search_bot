import logging
import os
import sys
from threading import Thread

from telegram import Update
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    Filters,
    MessageHandler,
    Updater,
)

from . import settings
from .commands import (
    callback_query_handler,
    engines_command,
    engines_command_more,
    image_search,
    show_id,
    start,
)

logger = logging.getLogger(__name__)


def error(update: Update, context: CallbackContext):
    """Log all errors from the telegram bot api

    Args:
        update (:obj:`telegram.update.Update`): Telegram update
        context (:obj:`telegram.ext.CallbackContext`): Bot context
    """
    logger.exception(context.error)
    logger.warning("Error caused by this update: %s" % (update))


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
        update.message.reply_text("Bot is restarting...")
        logger.info("Gracefully restarting...")
        Thread(target=stop_and_restart).start()

    dispatcher.add_handler(CommandHandler(("start", "help"), start))
    dispatcher.add_handler(CommandHandler("id", show_id))
    dispatcher.add_handler(CommandHandler("restart", restart, filters=Filters.user(user_id=settings.ADMIN_IDS)))
    dispatcher.add_handler(CommandHandler("engines", engines_command, run_async=True))
    dispatcher.add_handler(CommandHandler("more", engines_command_more, run_async=True))
    dispatcher.add_handler(CallbackQueryHandler(callback_query_handler, run_async=True))

    dispatcher.add_handler(
        MessageHandler(Filters.sticker | Filters.photo | Filters.video | Filters.document, image_search, run_async=True)
    )

    # log all errors
    dispatcher.add_error_handler(error)

    if settings.MODE["active"] == "webhook":
        updater.start_webhook(**settings.MODE["configuration"])
    else:
        updater.start_polling()
    logger.info("Started bot. Waiting for requests...")
    updater.idle()


if __name__ == "__main__":
    main()
