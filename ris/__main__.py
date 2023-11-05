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
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove
from aiohttp import ClientSession
from redis.asyncio.client import Redis
from redis.exceptions import ConnectionError

from ris import common
from ris.auto_search import SEARCH_ENGINES, find_existing_results, search_all_engines
from ris.data_provider import ProviderResult
from ris.files import prepare
from ris.redis import RedisStorage
from ris.s3 import S3Manager
from ris.utils import chunks, host_name, tagified_string

logger = logging.getLogger("ris")

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


@form_router.message(CommandStart())
async def command_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Form.search)
    await message.answer(
        "Hi there! Send me an image.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def send_result(message: Message, result: ProviderResult, search_engine: str = "") -> Message:
    main_file = result.main_file[0]
    text = f"<a href='{main_file}'>\u200b</a>\n\n"  # TODO: Send media group if we have multuple files
    provider = result.provider_id.split("-")[0]
    if search_engine:
        if provider_link := common.LINK_MAP.get(provider):
            text += f"Provided by {common.LINK_MAP[search_engine]} with {provider_link}\n\n"
        else:
            text += f"Provided by {common.LINK_MAP[search_engine]}\n\n"
    else:
        text += f"Provided by {common.LINK_MAP[provider]}\n\n"

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


async def search_for_file(message: Message, file_id: str, file_url: str) -> None:
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

    user_settings = await common.redis_storage.get_all_user_settings(user_id=message.from_user.id)  # type: ignore[union-attr]
    use_cache = user_settings.get("search_cache", True)

    found = False
    if not use_cache or not await common.redis_storage.check_no_found_entry(file_id):
        if use_cache and (results := await find_existing_results(file_id)):
            logger.info(f"Found {len(results)} existing results for {file_url}")
            await asyncio.gather(
                *(send_result(message, result) for result in results),
            )
            found = True
        else:
            logger.info(f"Searching for {file_url}...")
            async for result in search_all_engines(
                file_url,
                file_id,
                enabled_engines=user_settings.get("enabled_engines", set(SEARCH_ENGINES.keys())),  # type: ignore[arg-type]
            ):
                found = True
                await send_result(message, result.provider_result, result.search_provider)

    if not found:
        await common.redis_storage.add_no_found_entry(file_id)
        await reply.edit_text(f"No results found <a href='{file_url}'>\u200b</a>", reply_markup=full_keyboard)


@form_router.message(Form.search, F.photo | F.sticker)
async def search(message: Message, state: FSMContext) -> None:
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

    file_id = query.data.split(":")[1]
    file_url: str = query.message.reply_markup.inline_keyboard[1][0].url  # type: ignore[assignment]
    await query.answer("Searching ...")
    await search_for_file(query.message.reply_to_message, file_id, file_url)


async def settings_enabled_engines_dialogue(query: CallbackQuery, state: FSMContext) -> None:
    enabled_engines: set[str] = await common.redis_storage.get_user_setting(  # type: ignore[assignment]
        user_id=query.from_user.id, setting_id="enabled_engines", default=set(SEARCH_ENGINES.keys())
    )
    available_engines = {name: name in enabled_engines for name in SEARCH_ENGINES}
    if not query.message:
        query.answer("Something went wrong, please use /settings again.")
        return

    await query.message.edit_text(
        "<b>Enabled Engines</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=list(
                chunks(
                    [
                        InlineKeyboardButton(
                            text=f"{'✅' if enabled else '❌'} {name}",
                            callback_data=f"toggle_engine:{name}",
                        )
                        for name, enabled in available_engines.items()
                    ],
                    3,
                )
            )
            + [[InlineKeyboardButton(text="Back", callback_data="back")]],
        ),
    )


@form_router.callback_query(Form.enabled_engines)
async def callback_enabled_engines(query: CallbackQuery, state: FSMContext) -> None:
    if not query.message or not query.data:
        query.answer("Something went wrong, please use /settings again.")
        return

    if query.data == "back":
        await open_settings(query, state)
    elif query.data.startswith("toggle_engine:"):
        engine = query.data.split(":")[1]
        enabled_engines: set[str] = await common.redis_storage.get_user_setting(  # type: ignore[assignment]
            user_id=query.from_user.id, setting_id="enabled_engines", default=set(SEARCH_ENGINES.keys())
        )
        if engine in enabled_engines:
            enabled_engines.remove(engine)
        else:
            enabled_engines.add(engine)
        await common.redis_storage.set_user_setting(
            user_id=query.from_user.id, setting_id="enabled_engines", value=enabled_engines
        )
        await settings_enabled_engines_dialogue(query, state)


@form_router.callback_query(Form.settings)
async def callback_settings(query: CallbackQuery, state: FSMContext) -> None:
    if query.data == "enabled_engines":
        await state.set_state(Form.enabled_engines)
        await settings_enabled_engines_dialogue(query, state)
    elif query.data == "toggle_search_cache":
        current_settings: bool = await common.redis_storage.get_user_setting(  # type: ignore[assignment]
            user_id=query.from_user.id, setting_id="search_cache", default=True
        )
        await common.redis_storage.set_user_setting(
            user_id=query.from_user.id, setting_id="search_cache", value=not current_settings
        )
        await open_settings(query, state)
    elif query.data == "back":
        await state.set_state(Form.search)
        if not query.message:
            query.answer("Settings closed! Send me an image.")
        else:
            await query.message.edit_text("Settings closed! Send me an image.")


@form_router.message(Command("settings", ignore_case=True))
async def open_settings(message_or_query: Message | CallbackQuery, state: FSMContext) -> None:
    if isinstance(message_or_query, CallbackQuery):
        message: Message = message_or_query.message  # type: ignore[assignment]
        user = message_or_query.from_user
    else:
        message = message_or_query
        user = message.from_user  # type: ignore[assignment]

    current_settings = await common.redis_storage.get_all_user_settings(user_id=user.id)

    await state.set_state(Form.settings)
    reply_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Enabled Engines", callback_data="enabled_engines"),
                InlineKeyboardButton(
                    text=f"{'✅' if current_settings.get('search_cache', True) else '❌'}  Search Cache",
                    callback_data="toggle_search_cache",
                ),
            ],
            [
                InlineKeyboardButton(text="Back", callback_data="back"),
            ],
        ],
    )
    if message.from_user.id == (await message.bot.me()).id:  # type: ignore[union-attr]
        await message.edit_text(
            "<b>Settings</b>",
            reply_markup=reply_markup,
        )
    else:
        await message.reply(
            "<b>Settings</b>",
            reply_markup=reply_markup,
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

        await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
