import asyncio
import html
import io
import json
import logging
import os
import re
import sys
from pathlib import Path

from emoji import emojize
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.error import Forbidden
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import metrics, settings
from .commands import (
    callback_query_handler,
    file_handler,
    group_file_handler,
    help_command,
    id_command,
    on_added_to_group,
    onboard_callback_handler,
    search_command,
    settings_callback_handler,
    settings_command,
    start_command,
)
from .metrics import start_metrics_server

application: Application | None = None


class TelegramLogHandler(logging.Handler):
    """Forward WARNING+ log records to Telegram admin chats.

    Because this handler is invoked from arbitrary threads (via the logging
    framework), we schedule coroutines on the running event loop with
    ``asyncio.run_coroutine_threadsafe``.
    """

    prefixes = {
        logging.INFO: emojize(":blue_circle:"),
        logging.WARNING: emojize(":orange_circle:"),
        logging.ERROR: emojize(":red_circle:"),
        logging.FATAL: emojize(":cross_mark:"),
    }

    def __init__(self, *args, bot: Bot, loop: asyncio.AbstractEventLoop, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = bot
        self.loop = loop

    def emit(self, record: logging.LogRecord):
        try:
            prefix = self.prefixes.get(record.levelno, "")
            msg = f"{prefix} {self.format(record)}"
            for admin in settings.ADMIN_IDS:
                if len(msg) <= 4096:
                    coro = self.bot.send_message(admin, msg, parse_mode=ParseMode.HTML)
                else:
                    raw_text = super().format(record)
                    filename = f"error_{int(record.created)}_{record.levelname.lower()}.log"
                    log_data = io.BytesIO(raw_text.encode("utf-8"))
                    log_data.name = filename
                    suffix = "\n... [truncated]"
                    caption = msg[: 1024 - len(suffix)] + suffix if len(msg) > 1024 else msg
                    coro = self.bot.send_document(
                        admin, log_data, filename=filename, caption=caption, parse_mode=ParseMode.HTML
                    )
                asyncio.run_coroutine_threadsafe(coro, self.loop)
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

ADMIN_FILTER = filters.User(user_id=settings.ADMIN_IDS)


class RISBot:
    """Manages banned users. Stored as a plain class (no longer extends ExtBot)."""

    _banned_users: list[int] = []
    _banned_users_file: Path = Path("banned_users.json")

    def __init__(self):
        if self._banned_users_file.is_file():
            self._banned_users = json.loads(self._banned_users_file.read_text())

    async def ban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        metrics.commands_total.labels(command="ban").inc()
        args = update.message.text.strip("/").split(" ")
        if len(args) != 2:
            await update.message.reply_text("Usage: /ban <user_id>")
            return
        user_id = int(args[1])

        if user_id in self._banned_users:
            self._banned_users.remove(user_id)
            text = f"Removed user {user_id=} from banned users"
        else:
            self._banned_users.append(user_id)
            text = f"banned user {user_id=}"
        self._banned_users_file.write_text(json.dumps(self._banned_users))
        await update.message.reply_text(text)


ris_bot = RISBot()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log all errors from the telegram bot api."""
    if isinstance(context.error, Forbidden):
        return
    metrics.errors_total.labels(type=type(context.error).__name__).inc()
    logger.error("Uncaught exception in handler:", exc_info=context.error)


async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gracefully stop and replace the current process."""
    metrics.commands_total.labels(command="restart").inc()
    await update.message.reply_text("Bot is restarting...")
    logger.info("User requested restart")
    chat_id = update.effective_chat.id

    async def _stop_and_restart():
        if application is not None:
            await application.stop()
            await application.shutdown()
        logger.info("Restarting: starting...")
        os.execl(sys.executable, sys.executable, *sys.argv, f"restart={chat_id}")

    _restart_task = asyncio.create_task(_stop_and_restart())  # noqa: RUF006


async def post_init(app: Application) -> None:
    """Called after Application.initialize() — send restart/startup notifications."""
    loop = asyncio.get_running_loop()
    logging.getLogger("").addHandler(TelegramLogHandler(bot=app.bot, loop=loop, level=logging.WARNING))

    if match := re.match(r"restart=(\d+)", sys.argv[-1]):
        await app.bot.send_message(int(match.groups()[0]), "Restart successful!")

    for admin_id in settings.ADMIN_IDS:
        try:
            await app.bot.send_message(admin_id, emojize(":check_mark_button: Bot started successfully."))
        except Exception:
            logger.warning("Failed to notify admin %d of startup", admin_id)


def main():
    global application

    # Auto-migrate JSON config files to SQLite on first run
    from .config.db import migrate_json_files

    migrated = migrate_json_files(settings.CONFIG_DIR)
    if migrated:
        logger.info("Migrated %d JSON config files to SQLite", migrated)

    start_metrics_server()

    builder = Application.builder().token(settings.TELEGRAM_API_TOKEN)
    builder.concurrent_updates(settings.WORKERS)
    builder.post_init(post_init)
    app = builder.build()
    application = app

    # Handlers
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_added_to_group))
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("restart", restart_command, filters=ADMIN_FILTER))
    app.add_handler(CommandHandler("ban", ris_bot.ban_command, filters=ADMIN_FILTER), group=1)
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler(("settings", "conf", "pref"), settings_command))
    app.add_handler(CallbackQueryHandler(settings_callback_handler, pattern=r"^settings:"))
    app.add_handler(CallbackQueryHandler(onboard_callback_handler, pattern=r"^onboard:"))
    app.add_handler(CallbackQueryHandler(callback_query_handler))

    app.add_handler(
        MessageHandler(
            (filters.Sticker.ALL | filters.PHOTO | filters.VIDEO | filters.Document.ALL) & filters.ChatType.PRIVATE,
            file_handler,
        )
    )
    app.add_handler(
        MessageHandler(
            (filters.Sticker.ALL | filters.PHOTO | filters.VIDEO | filters.Document.ALL) & filters.ChatType.GROUPS,
            group_file_handler,
        )
    )

    app.add_error_handler(error_handler)

    if settings.MODE["active"] == "webhook":
        logger.info("Starting webhook")
        app.run_webhook(**settings.MODE["configuration"])
    else:
        logger.info("Start polling")
        app.run_polling()

    logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
