import asyncio
import logging
import os
import sys
from os import getenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.redis import RedisStorage as FSMRedisStorage
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageId,
    ReplyKeyboardRemove,
)
from aiohttp import ClientSession
from redis.asyncio.client import Redis
from redis.exceptions import ConnectionError

from ris import common
from ris.files import prepare
from ris.provider_engines import ProviderData
from ris.redis import RedisStorage
from ris.redis_models import UserSettings
from ris.s3 import S3Manager
from ris.search import SEARCH_ENGINES, search
from ris.utils import boji, chunks, host_name, human_readable_volume, tagified_string

logger = logging.getLogger("ris")

DEBUG_OPTIONS = bool(int(getenv("DEBUG_OPTIONS", 0)))
LOG_LEVEL = getenv("LOG_LEVEL", "INFO")

BASE_URL = getenv("BASE_URL")

if not BASE_URL:
    logger.fatal("BASE_URL env variable is not set")
    sys.exit(1)

form_router = Router()

simple_engines = {
    "Google": "https://www.google.com/searchbyimage?safe=off&sbisrc=tg&image_url={file_url}",
    "Google Lens": "https://lens.google.com/uploadbyurl?url={file_url}&safe=off",
    "Yandex": "https://yandex.com/images/search?url={file_url}&rpt=imageview",
    "TinEye": "https://tineye.com/search/?url={file_url}",
    "Bing": "https://www.bing.com/images/searchbyimage?FORM=IRSBIQ&cbir=sbi&imgurl={file_url}",
    # "Baidu": "https://graph.baidu.com/details?isfromtusoupc=1&tn=pc&queryImageUrl={file_url}",  # Has to be uploaded to Baidu first
    # "Sogou": "https://pic.sogou.com/ris?query={file_url}",   # Has to be uploaded to Sogou first
    "IQDB": "https://iqdb.org/?url={file_url}",
    "ASCII2D": "https://ascii2d.net/search/url/{file_url}",
    "SauceNAO": "https://saucenao.com/search.php?db=999&url={file_url}",
    "TraceMoe": "https://trace.moe/?auto&url={file_url}",
}


def get_simple_engine_buttons(file_url: str) -> list[list[InlineKeyboardButton]]:
    return list(
        chunks(
            [
                InlineKeyboardButton(text=name, url=url.format(file_url=file_url))
                for name, url in simple_engines.items()
            ],
            2,
        )
    )


class Form(StatesGroup):
    search = State()
    settings = State()
    enabled_engines = State()
    debug = State()
    broadcast = State()
    yes_no_dialogue = State()


@form_router.message(CommandStart())
async def command_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Form.search)
    await message.answer(
        "Hi there! Send me an image.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def send_result(message: Message, result: ProviderData) -> Message:
    main_file = result.main_files[0]  # TODO: Send media group if we have multuple files
    text = f"<a href='{main_file}'>\u200b</a>\n\n"

    provider = result.provider_id.split("-")[0]
    text += f"Found on {common.LINK_MAP[provider]}\n\n"

    for name, value in result.fields.items():
        name = name.title()
        if value is None:
            continue
        elif isinstance(value, bool):
            text += f"{name}: {'✔️' if value else '❌'}\n"
        elif isinstance(value, list):
            text += f"{name}: {tagified_string(value, 10)}\n"
        else:
            text += f"{name}: <code>{value}</code>\n"

    buttons = [
        InlineKeyboardButton(
            text=host_name(result.provider_link),
            url=result.provider_link,
        ),
    ]

    for link in filter(None, result.extra_links):
        buttons.append(
            InlineKeyboardButton(
                text=host_name(link),
                url=link,
            ),
        )

    return await message.reply(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=list(chunks(buttons, 3)),
        ),
    )


async def _search_and_send(message: Message, file_id: str, file_url: str) -> int:
    counter = 0
    try:
        settings: UserSettings = await UserSettings.fetch(
            common.redis_storage,
            user_id=message.from_user.id,  # type: ignore[union-attr]
            fill_keys=["cache_enabled", "enabled_engines", "best_results_only"],
        )

        async for result in search(image_id=file_id, image_url=file_url, user_settings=settings):
            counter += 1
            await send_result(message, result)
    except asyncio.TimeoutError as e:
        logger.warning("Search timed out for %s: %s", file_id, e)
    finally:
        return counter


async def search_for_file(message: Message, file_id: str, file_url: str) -> None:
    await common.redis_storage.incr_user_search_count(user_id=message.from_user.id)  # type: ignore[union-attr]
    full_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Search Again", callback_data=f"search_again:{file_id}")],
            [InlineKeyboardButton(text="Go To Image", url=file_url)],
        ]
        + get_simple_engine_buttons(file_url),
    )

    reply = await message.reply(
        f"Searching ... <a href='{file_url}'>\u200b</a>",
        reply_markup=full_keyboard,
    )

    if total_found := await asyncio.wait_for(_search_and_send(message, file_id, file_url), timeout=10):
        await reply.edit_text(
            f"Found {total_found} result{'s' if total_found != 1 else ''} <a href='{file_url}'>\u200b</a>",
            reply_markup=full_keyboard,
        )
    else:
        await reply.edit_text(f"No results found <a href='{file_url}'>\u200b</a>", reply_markup=full_keyboard)


@form_router.message(Form.search, F.photo | F.sticker)
async def search_handler(message: Message, state: FSMContext) -> None:
    if not message.photo and not message.sticker:
        return

    item = message.photo[-1] if message.photo else message.sticker

    file_id, prepared = await prepare(item, message.bot)  # type: ignore[arg-type]
    if not prepared:
        await message.reply("Something went wrong")
        return

    url = f"{BASE_URL}/{prepared}"
    await search_for_file(message, file_id, url)


@form_router.callback_query(Form.search)
async def search_again(query: CallbackQuery, state: FSMContext) -> None:
    if not query.message or not query.data or not query.message.reply_to_message or not query.message.reply_markup:
        query.answer("Something went wrong, please use /start again.")
        return

    if not query.data.startswith("search_again:"):
        await query.answer()
        await query.message.delete()
        return

    file_id = query.data.split(":")[1]
    file_url: str = query.message.reply_markup.inline_keyboard[1][0].url  # type: ignore[assignment]
    await query.answer("Searching ...")
    await search_for_file(query.message.reply_to_message, file_id, file_url)


@form_router.message(Command("settings", ignore_case=True))
async def open_settings(message: Message, state: FSMContext) -> None:
    if (message_id := (await state.get_data()).get("dialogue_message_id")) and message_id != message.message_id:
        await message.bot.delete_message(chat_id=message.chat.id, message_id=message_id)  # type: ignore[union-attr]
    await state.update_data(dialogue_message_id=None)
    await _open_settings(message, state)


async def _open_settings(message_or_query: Message | CallbackQuery, state: FSMContext) -> None:
    if isinstance(message_or_query, CallbackQuery):
        message: Message = message_or_query.message  # type: ignore[assignment]
        user_id = message_or_query.from_user.id
    else:
        message = message_or_query
        user_id = message.from_user.id  # type: ignore[union-attr]

    settings = await UserSettings.fetch(
        common.redis_storage,
        user_id=user_id,
        fill_keys=["best_results_only"],
    )
    logger.debug(f"[user_id={settings.user_id}] best_results_only={settings.best_results_only}")

    await state.set_state(Form.settings)
    buttons = [
        [
            InlineKeyboardButton(
                text=boji(settings.best_results_only) + " Show Best Results Only",
                callback_data="toggle_best_results_only",
            ),
            InlineKeyboardButton(text="Enabled Engines", callback_data="enabled_engines"),
        ],
        [
            InlineKeyboardButton(text="Close", callback_data="back"),
        ],
    ]

    if DEBUG_OPTIONS:
        buttons.insert(
            0,
            [
                InlineKeyboardButton(text="Debug Settings", callback_data="debug"),
            ],
        )

    reply_markup = InlineKeyboardMarkup(
        inline_keyboard=buttons,
    )
    bot: Bot = message.bot  # type: ignore[assignment]
    message_id = (await state.get_data()).get("dialogue_message_id")
    if message_id:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message_id,
            text="<b>Settings</b>",
            reply_markup=reply_markup,
        )
    else:
        message_id = await message.reply(
            "<b>Settings</b>",
            reply_markup=reply_markup,
        )
        await state.update_data(dialogue_message_id=message_id.message_id)


@form_router.callback_query(Form.settings)
async def callback_settings(query: CallbackQuery, state: FSMContext) -> None:
    if query.data == "enabled_engines":
        await state.set_state(Form.enabled_engines)
        await settings_enabled_engines_dialogue(query, state)
    elif query.data == "debug":
        await state.set_state(Form.debug)
        await open_debug(query, state)
    elif query.data == "toggle_best_results_only":
        settings = await UserSettings.fetch(
            common.redis_storage, user_id=query.from_user.id, fill_keys=["best_results_only"]
        )
        logger.debug(
            f"[user_id={settings.user_id}] toggling best_results_only from {settings.best_results_only} to"
            f" {not settings.best_results_only}"
        )
        settings.best_results_only = not settings.best_results_only
        await settings.save(["best_results_only"])
        await _open_settings(query, state)
    elif query.data == "back":
        await state.update_data(dialogue_message_id=None)
        await state.set_state(Form.search)
        if not query.message:
            query.answer("Settings closed! Send me an image.")
        else:
            await query.message.edit_text("Settings closed! Send me an image.")


async def settings_enabled_engines_dialogue(query: CallbackQuery, state: FSMContext) -> None:
    settings = await UserSettings.fetch(common.redis_storage, user_id=query.from_user.id)
    available_engines = {name: name in settings.enabled_engines for name in SEARCH_ENGINES}
    if not query.message:
        query.answer("Something went wrong, please use /settings again.")
        return

    bot: Bot = query.bot  # type: ignore[assignment]
    message_id = (await state.get_data()).get("dialogue_message_id")
    buttons = InlineKeyboardMarkup(
        inline_keyboard=list(
            chunks(
                [
                    InlineKeyboardButton(
                        text=f"{boji(enabled)} {name}",
                        callback_data=f"toggle_engine:{name}",
                    )
                    for name, enabled in available_engines.items()
                ],
                3,
            )
        )
        + [[InlineKeyboardButton(text="Back", callback_data="back")]],
    )

    if message_id:
        await bot.edit_message_text(
            chat_id=query.message.chat.id,
            message_id=message_id,
            text="<b>Enabled Engines</b>",
            reply_markup=buttons,
        )
    else:
        message_id = await query.message.reply(
            "<b>Enabled Engines</b>",
            reply_markup=buttons,
        )
        await state.update_data(dialogue_message_id=message_id.message_id)


@form_router.callback_query(Form.enabled_engines)
async def callback_enabled_engines(query: CallbackQuery, state: FSMContext) -> None:
    if not query.message or not query.data:
        query.answer("Something went wrong, please use /settings again.")
        return

    if query.data == "back":
        await _open_settings(query, state)
    elif query.data.startswith("toggle_engine:"):
        engine = query.data.split(":")[1]
        settings = await UserSettings.fetch(
            common.redis_storage, user_id=query.from_user.id, fill_keys=["enabled_engines"]
        )
        if engine in settings.enabled_engines:
            settings.enabled_engines.remove(engine)
        else:
            settings.enabled_engines.add(engine)
        await settings.save(["enabled_engines"])
        await settings_enabled_engines_dialogue(query, state)


async def open_debug(query: CallbackQuery, state: FSMContext) -> None:
    settings = await UserSettings.fetch(common.redis_storage, user_id=query.from_user.id, fill_keys=["cache_enabled"])
    await state.set_state(Form.debug)
    reply_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{'✅' if settings.cache_enabled else '❌'}  Search Cache",
                    callback_data="toggle_cache_enabled",
                ),
            ],
            [
                InlineKeyboardButton(text="\u200b", callback_data="noop"),
            ],
            [
                InlineKeyboardButton(text="Clear Not Found", callback_data="clear_not_found"),
                InlineKeyboardButton(text="Clear Provider Results", callback_data="clear_results"),
            ],
            [
                InlineKeyboardButton(text="Clear Results Fully", callback_data="clear_cache_full"),
            ],
            [
                InlineKeyboardButton(text="\u200b", callback_data="noop"),
            ],
            [
                InlineKeyboardButton(text="Broadcast", callback_data="broadcast"),
            ],
            [
                InlineKeyboardButton(text="Back", callback_data="back"),
            ],
        ],
    )
    total_searches = await common.redis_storage.get_total_search_count()
    searches_text = f"<pre>Searches: {total_searches}</pre>"

    total_users = await common.redis_storage.get_total_user_count()
    user_text = f"<pre>Users: {total_users}</pre>"

    cache_info = await common.redis_storage.get_cache_stats()
    cache_info_text = (
        f"<pre>Cache Info:\n  Provider Data:      {cache_info['provider_data']['entries']:>3} |"
        f" {human_readable_volume(cache_info['provider_data']['memory'])}\n  Provider Data Link:"
        f" {cache_info['provider_data_image_link']['entries']:>3} |"
        f" {human_readable_volume(cache_info['provider_data_image_link']['memory'])}\n  Not Found:         "
        f" {cache_info['not_found']['entries']:>3} | {human_readable_volume(cache_info['not_found']['memory'])}\n\n "
        f" Total:              {cache_info['total']['entries']:>3} |"
        f" {human_readable_volume(cache_info['total']['memory'])}\n</pre>"
    )

    text: str = f"<b>Debug Settings</b>\n\n{user_text}\n\n{searches_text}\n\n{cache_info_text}\n"

    message: Message = query.message  # type: ignore[assignment]
    bot: Bot = message.bot  # type: ignore[assignment]
    message_id = (await state.get_data()).get("dialogue_message_id")
    if message_id:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
        )
    else:
        message_id = await message.reply(
            text,
            reply_markup=reply_markup,
        )
        await state.update_data(dialogue_message_id=message_id.message_id)


@form_router.callback_query(Form.debug)
async def callback_debug(query: CallbackQuery, state: FSMContext) -> None:
    if query.data == "toggle_cache_enabled":
        settings = await UserSettings.fetch(
            common.redis_storage, user_id=query.from_user.id, fill_keys=["cache_enabled"]
        )
        settings.cache_enabled = not settings.cache_enabled
        await settings.save(["cache_enabled"])

        await open_debug(query, state)
    elif query.data == "clear_not_found":
        total = await common.redis_storage.clear_not_found_cache()
        await query.answer(f"Cleared {total} not found entries")
        if total != 0:
            await open_debug(query, state)
    elif query.data == "clear_results":
        total = await common.redis_storage.clear_provider_data_cache()
        await query.answer(f"Cleared {total} provider result entries")
        if total != 0:
            await open_debug(query, state)
    elif query.data == "clear_cache_full":
        total_not_found = await common.redis_storage.clear_not_found_cache()
        total_provider_data = await common.redis_storage.clear_provider_data_cache()
        await query.answer(f"Cleared {total_not_found} not found and {total_provider_data} provider result entries")
        if total_not_found + total_provider_data != 0:
            await open_debug(query, state)
    elif query.data == "back":
        await state.set_state(Form.settings)
        await _open_settings(query, state)
    elif query.data == "noop":
        await query.answer()
    elif query.data == "broadcast":
        await broadcast_dialogue(query, state)


async def broadcast_dialogue(query_or_message: CallbackQuery | Message, state: FSMContext) -> None:
    if isinstance(query_or_message, CallbackQuery):
        if not query_or_message.message:
            query_or_message.answer("Something went wrong, please use /settings again.")
            return
        chat_id = query_or_message.message.chat.id if query_or_message.message else query_or_message.from_user.id
    else:
        chat_id = query_or_message.chat.id

    await state.set_state(Form.broadcast)
    settings = await UserSettings.fetch(
        common.redis_storage,
        user_id=query_or_message.from_user.id,  # type: ignore[union-attr]
        fill_keys=["broadcast_message_id"],
    )

    buttons = [[InlineKeyboardButton(text="Back", callback_data="back")]]

    if settings.broadcast_message_id:
        buttons.insert(0, [InlineKeyboardButton(text="📨 Send Broadcast", callback_data="ask_send_broadcast")])

    bot: Bot = query_or_message.bot  # type: ignore[assignment]
    message_id = (await state.get_data()).get("dialogue_message_id")
    text: str = (
        "<b>Broadcast</b>\n\nSend a message to all users. This can be used to send important updates or"
        " announcements.\n\n"
    )
    if message_id:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    else:
        message = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
        await state.update_data(dialogue_message_id=message.message_id)


@form_router.message(Form.broadcast)
async def process_broadcast(message: Message, state: FSMContext) -> None:
    settings = await UserSettings.fetch(common.redis_storage, user_id=message.from_user.id, fill_keys=[""])  # type: ignore[union-attr]
    settings.broadcast_message_id = message.message_id
    settings.broadcast_message_chat_id = message.chat.id
    await settings.save(["broadcast_message_id", "broadcast_message_chat_id"])

    await broadcast_dialogue(message, state)


@form_router.callback_query(Form.broadcast)
async def callback_broadcast(query: CallbackQuery, state: FSMContext) -> None:
    if query.data == "back":
        await open_debug(query, state)
    if query.data == "ask_send_broadcast":
        bot: Bot = query.bot  # type: ignore[assignment]
        bc_message = await preview_broadcast(bot, query.from_user.id, state)
        if not bc_message:
            await query.answer("Something went wrong, please use /settings again.")
            return

        await state.set_state(Form.yes_no_dialogue)
        await bot.send_message(
            chat_id=query.message.chat.id if query.message else query.from_user.id,
            reply_to_message_id=bc_message.message_id,
            text="Are you sure you want to send this message to all users?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Yes", callback_data="yes:send_broadcast"),
                        InlineKeyboardButton(text="No", callback_data="no:abort_broadcast"),
                    ],
                ],
            ),
        )
        await query.answer()


async def preview_broadcast(bot: Bot, chat_id: int, state: FSMContext) -> MessageId | None:
    settings = await UserSettings.fetch(
        common.redis_storage, user_id=chat_id, fill_keys=["broadcast_message_id", "broadcast_message_chat_id"]
    )
    if not settings.broadcast_message_id or not settings.broadcast_message_chat_id:
        return None

    message_id = await bot.copy_message(
        chat_id=chat_id,
        from_chat_id=settings.broadcast_message_chat_id,
        message_id=settings.broadcast_message_id,
    )

    await state.update_data(broadcast_preview_message_id=message_id.message_id)

    return message_id


async def broadcast_cleanup(query: CallbackQuery, state: FSMContext, text: str = "") -> None:
    data = await state.get_data()
    bot: Bot = query.bot  # type: ignore[assignment]
    chat_id = query.message.chat.id or query.from_user.id  # type: ignore[union-attr]

    if message_id := data.get("dialogue_message_id"):
        await bot.delete_message(
            chat_id=chat_id,
            message_id=message_id,
        )
        await state.update_data(dialogue_message_id=None)

    if query.message:
        if text:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=query.message.message_id,
                text=text,
            )
        else:
            await bot.delete_message(
                chat_id=query.message.chat.id,
                message_id=query.message.message_id,
            )

    if preview_message_id := data.get("broadcast_preview_message_id"):
        await bot.delete_message(
            chat_id=query.from_user.id,
            message_id=preview_message_id,
        )
        await state.update_data(broadcast_preview_message_id=None)


@form_router.callback_query(Form.yes_no_dialogue)
async def callback_yes_no_dialogue(query: CallbackQuery, state: FSMContext) -> None:
    if query.data == "yes:send_broadcast":
        await state.set_state(Form.broadcast)
        await query.answer("Sending broadcast ...")
        await broadcast_cleanup(query, state, "Sending broadcast ...")
        await broadcast_dialogue(query, state)
        await send_broadcast(query, state)
    elif query.data == "no:abort_broadcast":
        await state.set_state(Form.broadcast)
        await query.answer("You aborted sending the broadcast")
        await broadcast_cleanup(query, state, "You aborted sending the broadcast.")
        await broadcast_dialogue(query, state)


async def send_broadcast(query: CallbackQuery, state: FSMContext) -> None:
    settings = await UserSettings.fetch(
        common.redis_storage,
        user_id=query.from_user.id,
        fill_keys=["broadcast_message_id", "broadcast_message_chat_id"],
    )
    bot: Bot = query.bot  # type: ignore[assignment]
    chat_id = query.message.chat.id  # type: ignore[union-attr]

    if not settings.broadcast_message_id or not settings.broadcast_message_chat_id:
        await bot.send_message(
            chat_id=chat_id,
            text="Something went wrong, please use /settings again.",
        )
        return

    print("Sending broadcast")
    print(settings.broadcast_message_id, settings.broadcast_message_chat_id)

    for user_id in await common.redis_storage.get_users():
        print(f"Sending to {user_id}")
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=settings.broadcast_message_chat_id,
            message_id=settings.broadcast_message_id,
        )


async def main() -> None:
    TOKEN = getenv("BOT_TOKEN")
    if not TOKEN:
        logger.fatal("BOT_TOKEN env variable is not set")
        sys.exit(1)

    redis = Redis(decode_responses=True)
    try:
        await redis.ping()
        logger.info("Connected to Redis")
    except ConnectionError as e:
        logger.fatal(f"Cannot connect to Redis: {e}")
        sys.exit(1)
    bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=FSMRedisStorage(redis))
    dp.include_router(form_router)

    try:
        s3 = S3Manager(
            access_key=os.environ["S3_ACCESS_KEY"],
            secret_key=os.environ["S3_SECRET_KEY"],
            endpoint_url=os.environ["S3_ENDPOINT_URL"],
            default_bucket=os.environ["S3_DEFAULT_BUCKET"],
        )
    except KeyError as e:
        logger.fatal(f"Missing env variable {e}")
        sys.exit(1)

    async with ClientSession() as session:
        # Set up common variables
        common.http_session = session
        common.redis = redis
        common.s3 = s3
        common.redis_storage = RedisStorage(redis)

        await bot.set_my_commands(
            commands=[
                BotCommand(command="start", description="Start the bot"),
                BotCommand(command="settings", description="Open settings"),
            ]
        )

        await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging._nameToLevel.get(LOG_LEVEL, logging.INFO), stream=sys.stdout)
    asyncio.run(main())
