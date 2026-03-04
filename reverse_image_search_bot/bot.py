import asyncio
import html
import io
import json
import logging
from pathlib import Path

from emoji import emojize
from telegram import Bot, BotCommand, BotCommandScopeChat, BotCommandScopeDefault, Update
from telegram.constants import ParseMode
from telegram.error import Forbidden
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
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


_BANNED_USERS_JSON = Path("banned_users.json")


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.message and update.message.text
    metrics.commands_total.labels(command="ban").inc()
    args = update.message.text.strip("/").split(" ")
    if len(args) != 2:
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    user_id = int(args[1])

    banned: list[int] = context.bot_data.setdefault("banned_users", [])
    if user_id in banned:
        banned.remove(user_id)
        text = f"Removed user {user_id=} from banned users"
    else:
        banned.append(user_id)
        text = f"banned user {user_id=}"
    await update.message.reply_text(text)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log all errors from the telegram bot api."""
    if isinstance(context.error, Forbidden):
        return
    metrics.errors_total.labels(type=type(context.error).__name__).inc()
    logger.error("Uncaught exception in handler:", exc_info=context.error)


_PUBLIC_COMMANDS = [
    BotCommand("search", "Search for image source (reply to image)"),
    BotCommand("settings", "Configure bot behaviour for this chat"),
    BotCommand("help", "Show help"),
    BotCommand("start", "Start the bot"),
]

_LOCALISED_COMMANDS: dict[str, list[BotCommand]] = {
    "ru": [
        BotCommand("search", "Поиск источника изображения (ответьте на изображение)"),
        BotCommand("settings", "Настройки бота для этого чата"),
        BotCommand("help", "Показать справку"),
        BotCommand("start", "Запустить бота"),
    ],
    "zh": [
        BotCommand("search", "搜索图片来源（回复图片）"),
        BotCommand("settings", "配置此聊天的机器人设置"),
        BotCommand("help", "显示帮助"),
        BotCommand("start", "启动机器人"),
    ],
    "es": [
        BotCommand("search", "Buscar origen de imagen (responder a imagen)"),
        BotCommand("settings", "Configurar el bot para este chat"),
        BotCommand("help", "Mostrar ayuda"),
        BotCommand("start", "Iniciar el bot"),
    ],
    "it": [
        BotCommand("search", "Cerca l'origine dell'immagine (rispondi a un'immagine)"),
        BotCommand("settings", "Configura il bot per questa chat"),
        BotCommand("help", "Mostra aiuto"),
        BotCommand("start", "Avvia il bot"),
    ],
    "ar": [
        BotCommand("search", "البحث عن مصدر الصورة (رد على صورة)"),
        BotCommand("settings", "إعدادات البوت لهذه المحادثة"),
        BotCommand("help", "عرض المساعدة"),
        BotCommand("start", "تشغيل البوت"),
    ],
    "ja": [
        BotCommand("search", "画像のソースを検索（画像に返信）"),
        BotCommand("settings", "このチャットのボット設定"),
        BotCommand("help", "ヘルプを表示"),
        BotCommand("start", "ボットを起動"),
    ],
    "de": [
        BotCommand("search", "Bildquelle suchen (auf Bild antworten)"),
        BotCommand("settings", "Bot-Einstellungen für diesen Chat"),
        BotCommand("help", "Hilfe anzeigen"),
        BotCommand("start", "Bot starten"),
    ],
}

_ADMIN_COMMANDS = [
    *_PUBLIC_COMMANDS,
    BotCommand("ban", "Ban/unban a user by ID"),
    BotCommand("id", "Show current chat info"),
]


async def _set_bot_commands(app: Application) -> None:
    """Register bot command menus with Telegram.

    Public commands are set for the default scope with localised variants.
    Admin commands (including /ban and /id) are set per admin private chat
    via BotCommandScopeChat (English only).
    """
    await app.bot.set_my_commands(_PUBLIC_COMMANDS, scope=BotCommandScopeDefault())
    for lang, commands in _LOCALISED_COMMANDS.items():
        try:
            await app.bot.set_my_commands(commands, scope=BotCommandScopeDefault(), language_code=lang)
        except Exception:
            logger.warning("Failed to set %s commands", lang)
    for admin_id in settings.ADMIN_IDS:
        try:
            await app.bot.set_my_commands(_ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:
            logger.warning("Failed to set admin commands for %d", admin_id)


async def post_init(app: Application) -> None:
    """Called after Application.initialize() — send restart/startup notifications."""
    loop = asyncio.get_running_loop()
    logging.getLogger("").addHandler(TelegramLogHandler(bot=app.bot, loop=loop, level=logging.WARNING))

    # One-time migration: banned_users.json → bot_data
    if _BANNED_USERS_JSON.is_file():
        try:
            users = json.loads(_BANNED_USERS_JSON.read_text())
            if users:
                banned: list[int] = app.bot_data.setdefault("banned_users", [])
                for uid in users:
                    if uid not in banned:
                        banned.append(uid)
            _BANNED_USERS_JSON.rename(_BANNED_USERS_JSON.with_suffix(".json.bak"))
            logger.info("Migrated banned_users.json → bot_data (%d users)", len(users))
        except Exception:
            logger.warning("Failed to migrate banned_users.json", exc_info=True)

    await _set_bot_commands(app)

    for admin_id in settings.ADMIN_IDS:
        try:
            await app.bot.send_message(admin_id, emojize(":check_mark_button: Bot started successfully."))
        except Exception:
            logger.warning("Failed to notify admin %d of startup", admin_id)


def main():
    global application

    # Auto-migrate JSON config files to SQLite on first run
    from .config.db import migrate_json_files

    migrated = migrate_json_files(settings.OLD_CONFIG_DIR)
    if migrated:
        logger.info("Migrated %d JSON config files to SQLite", migrated)

    start_metrics_server()

    persistence = PicklePersistence(filepath=str(settings.PERSISTENCE_PATH))
    builder = Application.builder().token(settings.TELEGRAM_API_TOKEN)
    builder.persistence(persistence)
    builder.concurrent_updates(settings.CONCURRENT_UPDATES)
    builder.post_init(post_init)
    app = builder.build()
    application = app

    # Handlers
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_added_to_group))
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("ban", ban_command, filters=ADMIN_FILTER), group=1)
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
