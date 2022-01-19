import html
import logging
import os
import re
import sys
from threading import Thread

from emoji import emojize
from telegram import Bot, Update
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    Filters,
    MessageHandler,
    Updater,
)
from telegram.parsemode import ParseMode

from . import settings
from .commands import (
    callback_query_handler,
    engines_command,
    file_handler,
    help_command,
    id_command,
    more_command,
)


class TelegramLogHandler(logging.Handler):
    prefixes = {
        logging.INFO: emojize(":blue_circle:"),
        logging.WARNING: emojize(":orange_circle:"),
        logging.ERROR: emojize(":red_circle:"),
        logging.FATAL: emojize(":cross_mark:"),
    }

    def __init__(self, *args, bot: Bot, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = bot

    def emit(self, record: logging.LogRecord):
        msg = self.prefixes.get(record.levelno, "") + " " + self.format(record)

        for admin in settings.ADMIN_IDS:
            self.bot.send_message(admin, msg, parse_mode=ParseMode.HTML)

    def format(self, record: logging.LogRecord):
        result = html.escape(super().format(record))
        if record.exc_info:
            parts = result.split("\n", 1)
            return f"{parts[0]}\n<pre>{parts[1]}</pre>"
        return result


logger = logging.getLogger(__name__)

ADMIN_FILTER = Filters.user(user_id=settings.ADMIN_IDS)


def error(update: Update, context: CallbackContext):
    """Log all errors from the telegram bot api"""
    logger.exception(context.error)
    logger.warning("Error caused by this update: %s" % (update))


def main():
    updater = Updater(settings.TELEGRAM_API_TOKEN)
    dispatcher = updater.dispatcher

    def stop_and_restart(chat_id: int):
        """Gracefully stop the Updater and replace the current process with a new one."""
        logger.info("Restarting: stopping...")
        updater.stop()
        logger.info("Restarting: starting...")
        os.execl(sys.executable, sys.executable, *sys.argv, "restart=%d" % chat_id)

    def restart_command(update: Update, context: CallbackContext):
        """Start the restarting process"""
        update.message.reply_text("Bot is restarting...")
        logger.info("User requested restart")
        Thread(target=stop_and_restart, args=(update.effective_chat.id,)).start()  # type: ignore

    dispatcher.add_handler(CommandHandler(("start", "help"), help_command))
    dispatcher.add_handler(CommandHandler("id", id_command))
    dispatcher.add_handler(CommandHandler("restart", restart_command, filters=ADMIN_FILTER))
    dispatcher.add_handler(CommandHandler("engines", engines_command, run_async=True))
    dispatcher.add_handler(CommandHandler("more", more_command, run_async=True))
    dispatcher.add_handler(CallbackQueryHandler(callback_query_handler, run_async=True))

    logging.getLogger("").addHandler(TelegramLogHandler(bot=updater.bot, level=logging.WARNING))

    dispatcher.add_handler(
        MessageHandler(Filters.sticker | Filters.photo | Filters.video | Filters.document, file_handler, run_async=True)
    )

    # log all errors
    dispatcher.add_error_handler(error)

    print(sys.argv[-1])
    if match := re.match(r"restart=(\d+)", sys.argv[-1]):
        updater.bot.send_message(int(match.groups()[0]), "Restart successful!")

    if settings.MODE["active"] == "webhook":
        updater.start_webhook(**settings.MODE["configuration"])
    else:
        updater.start_polling()
    logger.info("Started bot. Waiting for requests...")
    updater.idle()


if __name__ == "__main__":
    main()
