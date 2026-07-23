import asyncio
import html
import io
import json
import logging
from pathlib import Path

from emoji import emojize
from telegram import (
    Bot,
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    Defaults,
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
from .commands.feedback import (
    WAITING_FOR_FEEDBACK,
    feedback_cancel,
    feedback_command,
    feedback_received,
    feedback_reply_handler,
)
from .commands.report import report_command, reports_command
from .config import abuse
from .i18n import available_languages, t
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

    banned: list[int] = context.bot_data.setdefault("banned_users", [])

    # No argument → list currently banned users, flagging any who have a filed report.
    if len(args) < 2 or not args[1].strip():
        if not banned:
            await update.message.reply_text("No users are currently banned.")
            return
        lines = ["<b>Banned users:</b>"]
        for uid in banned:
            flag = " 🚩 reported" if abuse.has_report(uid) else ""
            lines.append(f"<code>{uid}</code>{flag}")
        # Telegram caps messages at 4096 chars — chunk on line boundaries.
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 4000:
                await update.message.reply_html(chunk)
                chunk = ""
            chunk += line + "\n"
        if chunk:
            await update.message.reply_html(chunk)
        return

    try:
        user_id = int(args[1])
    except ValueError:
        await update.message.reply_text(t("commands.ban_usage"))
        return

    if user_id in banned:
        banned.remove(user_id)
        abuse.set_banned(user_id, False)
        text = f"Removed user {user_id=} from banned users"
    else:
        banned.append(user_id)
        abuse.set_banned(user_id, True)
        text = f"banned user {user_id=}"
    await update.message.reply_text(text)


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Report how many files a user has uploaded. Accepts a user ID or a filename.

    ``/check <user_id>`` counts directly; ``/check <filename>`` resolves the
    uploader from the abuse DB first (for Cloudflare abuse reports, which
    only give the on-disk filename).
    """
    assert update.message and update.message.text
    metrics.commands_total.labels(command="check").inc()
    args = update.message.text.strip("/").split(" ")
    if len(args) < 2 or not args[1].strip():
        await update.message.reply_text("Usage: /check <user_id | filename>")
        return

    arg = args[1].strip()
    if arg.isdigit():
        user_id: int | None = int(arg)
        source = f"user <code>{user_id}</code>"
    else:
        user_id = abuse.find_user_by_filename(arg)
        if user_id is None:
            await update.message.reply_text(f"No uploader found for file: {arg}")
            return
        source = f"file <code>{html.escape(arg)}</code> → user <code>{user_id}</code>"

    count = abuse.count_files(user_id)
    user = abuse.get_user(user_id)
    banned = user_id in context.bot_data.get("banned_users", [])
    parts = [f"{source}", f"Uploaded files: <b>{count}</b>"]
    if user and user.get("username"):
        parts.append(f"Username: @{html.escape(user['username'])}")
    parts.append(f"Banned: {'yes' if banned else 'no'}")
    if abuse.has_report(user_id):
        parts.append("🚩 Has a filed report")
    await update.message.reply_html("\n".join(parts))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log all errors from the telegram bot api."""
    chat = getattr(update, "effective_chat", None) if isinstance(update, Update) else None

    if isinstance(context.error, Forbidden):
        return

    if isinstance(context.error, BadRequest):
        error_msg = str(context.error).lower()
        if "chat_write_forbidden" in error_msg:
            metrics.track_write_forbidden(chat)
            return
        if "rights" in error_msg:
            metrics.track_permission_error(chat)
            return

    if isinstance(context.error, RetryAfter):
        metrics.track_retry_after(context.error.retry_after)
        return

    metrics.errors_total.labels(type=type(context.error).__name__).inc()
    logger.error("Uncaught exception in handler:", exc_info=context.error)


_PUBLIC_COMMANDS = [
    BotCommand("search", t("bot_commands.search")),
    BotCommand("settings", t("bot_commands.settings")),
    BotCommand("feedback", t("bot_commands.feedback")),
    BotCommand("help", t("bot_commands.help")),
    BotCommand("start", t("bot_commands.start")),
]

_ADMIN_COMMANDS = [
    *_PUBLIC_COMMANDS,
    BotCommand("ban", "Ban/unban a user by ID, or list banned users"),
    BotCommand("check", "Count a user's uploads (by user ID or filename)"),
    BotCommand("report", "Prepare an encrypted NCMEC report for a user"),
    BotCommand("reports", "List all abuse reports and their status"),
    BotCommand("id", "Show current chat info"),
]


async def _set_bot_commands(app: Application) -> None:
    """Register bot command menus with Telegram.

    Public commands are set for the default scope with localised variants
    driven by TOML string catalogs. Admin commands (including /ban and /id)
    are set per admin private chat via BotCommandScopeChat (English only).
    """
    await app.bot.set_my_commands(_PUBLIC_COMMANDS, scope=BotCommandScopeDefault())
    for lang_code in available_languages():
        if lang_code == "en":
            continue
        commands = [
            BotCommand("search", t("bot_commands.search", lang_code)),
            BotCommand("settings", t("bot_commands.settings", lang_code)),
            BotCommand("feedback", t("bot_commands.feedback", lang_code)),
            BotCommand("help", t("bot_commands.help", lang_code)),
            BotCommand("start", t("bot_commands.start", lang_code)),
        ]
        try:
            await app.bot.set_my_commands(commands, scope=BotCommandScopeDefault(), language_code=lang_code)
        except Exception:
            logger.warning("Failed to set %s commands", lang_code)
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

    # Sync durable ban list from the abuse DB into bot_data. Redundancy guard:
    # if bot_data ever loses banned_users (e.g. a cleared pickle), the DB restores
    # it on the next start. Union of both sources — neither shrinks the other.
    try:
        banned: list[int] = app.bot_data.setdefault("banned_users", [])
        db_banned = abuse.banned_user_ids()
        added = 0
        for uid in db_banned:
            if uid not in banned:
                banned.append(uid)
                added += 1
        # Also push any bot_data-only bans back into the DB so they're durable.
        for uid in banned:
            if uid not in db_banned:
                abuse.set_banned(uid, True)
        logger.info("Synced ban list from abuse DB (%d in DB, %d restored to memory)", len(db_banned), added)
    except Exception:
        logger.warning("Failed to sync ban list from abuse DB", exc_info=True)

    await _set_bot_commands(app)
    await _start_report_server(app)

    for admin_id in settings.ADMIN_IDS:
        try:
            await app.bot.send_message(admin_id, t("commands.bot_started"))
        except Exception:
            logger.warning("Failed to notify admin %d of startup", admin_id)


# Module-level handle for the aiohttp report-server runner (see note below).
_report_runner = None


async def _start_report_server(app: Application) -> None:
    """Start the aiohttp report webview server if enabled.

    The admin-only Mini App menu button is NOT set here — it is set per-report by
    the /report command (set_chat_menu_button to that specific report's URL), so
    tapping it launches the report as a Mini App with signed initData.
    """
    if not settings.REPORT_SERVER_ENABLED:
        return
    try:
        from .abuse_report.server import start_report_server

        runner = await start_report_server(bot=app.bot, bot_data=app.bot_data)
        if runner is not None:
            # Keep a reference so the runner isn't garbage collected. Never put
            # it in bot_data: an AppRunner is unpicklable, and one unpicklable
            # value makes every PicklePersistence flush fail silently, freezing
            # feedback_replies/banned_users on disk.
            global _report_runner
            _report_runner = runner
    except Exception:
        logger.warning("Failed to start report server", exc_info=True)


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
    # Users delete their message mid-search — send the reply standalone
    # instead of failing with "Message to be replied not found".
    builder.defaults(Defaults(allow_sending_without_reply=True))
    builder.post_init(post_init)
    app = builder.build()
    application = app

    # Handlers
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_added_to_group))
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    id_filter = filters.Regex(r"^/id(?:@\S+)?$") & (filters.UpdateType.MESSAGES | filters.UpdateType.CHANNEL_POST)
    app.add_handler(MessageHandler(id_filter, id_command))
    app.add_handler(CommandHandler("ban", ban_command, filters=ADMIN_FILTER), group=1)
    app.add_handler(CommandHandler("check", check_command, filters=ADMIN_FILTER), group=1)
    app.add_handler(CommandHandler("report", report_command, filters=ADMIN_FILTER), group=1)
    app.add_handler(CommandHandler("reports", reports_command, filters=ADMIN_FILTER), group=1)
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler(("settings", "conf", "pref"), settings_command))

    # Feedback conversation handler
    feedback_handler = ConversationHandler(
        entry_points=[CommandHandler("feedback", feedback_command)],  # ty: ignore[invalid-argument-type]
        states={
            WAITING_FOR_FEEDBACK: [
                CommandHandler("cancel", feedback_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_received),
            ],
        },  # ty: ignore[invalid-argument-type]
        fallbacks=[CommandHandler("cancel", feedback_cancel)],  # ty: ignore[invalid-argument-type]
        conversation_timeout=300,  # 5 minute timeout
    )
    app.add_handler(feedback_handler)  # ty: ignore[invalid-argument-type]

    # Feedback reply handler — allows admins and users to reply back and forth
    app.add_handler(
        MessageHandler(
            filters.REPLY & filters.TEXT & filters.ChatType.PRIVATE,
            feedback_reply_handler,
        ),
        group=2,
    )

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
