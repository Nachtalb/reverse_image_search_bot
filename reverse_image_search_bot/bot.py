import html
import io
import json
import logging
import os
import re
import sys
from pathlib import Path
from threading import Thread

from emoji import emojize
from telegram import Bot, Update
from telegram.error import Unauthorized
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    Dispatcher,
    ExtBot,
    Filters,
    JobQueue,
    MessageHandler,
    Updater,
)
from telegram.parsemode import ParseMode
from telegram.utils.request import Request

from . import settings
from .commands import (
    auto_search_command,
    callback_query_handler,
    credits_command,
    file_handler,
    help_command,
    id_command,
    search_command,
    settings_callback_handler,
    settings_command,
    start_command,
    tips_command,
)


job_queue: JobQueue = None  # type: ignore


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
        try:
            prefix = self.prefixes.get(record.levelno, "")
            msg = f"{prefix} {self.format(record)}"
            for admin in settings.ADMIN_IDS:
                if len(msg) <= 4096:
                    self.bot.send_message(admin, msg, parse_mode=ParseMode.HTML)
                else:
                    raw_text = super().format(record)  # plain text, no HTML
                    filename = f"error_{int(record.created)}_{record.levelname.lower()}.log"
                    log_data = io.BytesIO(raw_text.encode("utf-8"))
                    log_data.name = filename
                    suffix = "\n... [truncated]"
                    caption = msg[:1024 - len(suffix)] + suffix if len(msg) > 1024 else msg
                    self.bot.send_document(admin, log_data, filename=filename, caption=caption, parse_mode=ParseMode.HTML)
        except Exception:
            pass

    def format(self, record: logging.LogRecord):
        result = html.escape(super().format(record))
        if record.exc_info:
            parts = result.split("\n", 1)
            first_line = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
            return f"{first_line}\n<pre>{rest}</pre>"
        return result


logger = logging.getLogger(__name__)

ADMIN_FILTER = Filters.user(user_id=settings.ADMIN_IDS)


class RISBot(ExtBot):
    _banned_users: list[int] = []
    _banned_users_file: Path = Path("banned_users.json")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self._banned_users_file.is_file():
            self._banned_users = json.loads(self._banned_users_file.read_text())

    def _ban_user(self, update: Update, _: CallbackContext):
        args = update.message.text.strip("/").split(" ")
        if len(args) != 2:
            update.message.reply_text("Usage: /ban <user_id>")
            return
        user_id = int(args[1])

        if user_id in self._banned_users:
            self._banned_users.remove(user_id)
            text = f"Removed user {user_id=} from banned users"
        else:
            self._banned_users.append(user_id)
            text = f"banned user {user_id=}"
        self._banned_users_file.write_text(json.dumps(self._banned_users))
        update.message.reply_text(text)


def error_logger(update: Update, context: CallbackContext, *_, **__):
    """Log all errors from the telegram bot api"""
    if isinstance(context.error, Unauthorized):
        return
    logger.error("Uncaught exception in handler:", exc_info=context.error)


def main():
    global job_queue
    _request = Request(con_pool_size=settings.CON_POOL_SIZE)
    bot = RISBot(settings.TELEGRAM_API_TOKEN, request=_request, arbitrary_callback_data=False)
    updater = Updater(bot=bot, workers=settings.WORKERS)
    dispatcher: Dispatcher = updater.dispatcher
    job_queue = updater.job_queue

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

    dispatcher.add_handler(CommandHandler("start", start_command))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("id", id_command))
    dispatcher.add_handler(CommandHandler("tips", tips_command))
    dispatcher.add_handler(CommandHandler("restart", restart_command, filters=ADMIN_FILTER))
    dispatcher.add_handler(
        CommandHandler("ban", bot._ban_user, filters=ADMIN_FILTER), group=1
    )
    dispatcher.add_handler(CommandHandler(("credits", "credit"), credits_command, run_async=True))
    dispatcher.add_handler(CommandHandler("search", search_command, run_async=True))
    dispatcher.add_handler(CommandHandler("auto_search", auto_search_command, filters=Filters.chat_type.private, run_async=True))
    dispatcher.add_handler(CommandHandler(("settings", "conf", "pref"), settings_command, run_async=True))
    dispatcher.add_handler(CallbackQueryHandler(settings_callback_handler, pattern=r"^settings:", run_async=True))
    dispatcher.add_handler(CallbackQueryHandler(callback_query_handler, run_async=True))

    logging.getLogger("").addHandler(TelegramLogHandler(bot=updater.bot, level=logging.WARNING))

    dispatcher.add_handler(
        MessageHandler(
            (Filters.sticker | Filters.photo | Filters.video | Filters.document) & Filters.chat_type.private,
            file_handler,
            run_async=True,
        )
    )

    # log all errors
    dispatcher.add_error_handler(error_logger)

    if match := re.match(r"restart=(\d+)", sys.argv[-1]):
        updater.bot.send_message(int(match.groups()[0]), "Restart successful!")

    if settings.MODE["active"] == "webhook":
        logger.info("Starting webhook")
        updater.start_webhook(**settings.MODE["configuration"])
    else:
        logger.info("Start polling")
        updater.start_polling()
    logger.info("Started bot. Waiting for requests...")
    updater.idle()


if __name__ == "__main__":
    main()
