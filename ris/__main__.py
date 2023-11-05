import asyncio
import logging
import os
import sys
from os import getenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.redis import RedisStorage as FSMRedisStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove
from aiohttp import ClientSession
from redis.asyncio.client import Redis
from redis.exceptions import ConnectionError

from ris import common
from ris.auto_search import find_existing_results, saucenao_search
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


@form_router.message(CommandStart())
async def command_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Form.search)
    await message.answer(
        "Hi there! Send me an image.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def send_result(message: Message, result: ProviderResult, search_engine: str = "") -> Message:
    text = f"<a href='{result.main_file}'>\u200b</a>\n\n"
    provider = result.provider_id.split("-")[0]
    if search_engine:
        text += f"Provided by {common.LINK_MAP[search_engine]} with {common.LINK_MAP[provider]}\n\n"
    else:
        text += f"Provided by {common.LINK_MAP[provider]}\n\n"

    for name, value in result.fields.items():
        if isinstance(value, bool):
            text += f"{name}: {'✔️' if value else '❌'}\n"
        elif isinstance(value, list):
            text += f"{name}: {tagified_string(value, 10)}\n"
        else:
            text += f"{name}: `{value}`\n"

    buttons = [
        InlineKeyboardButton(
            text=host_name(result.provider_link),
            url=result.provider_link,
        ),
    ]

    for link in result.extra_links:
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
    full_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Go To Image", url=url)]] + get_simple_engine_buttons(url),
    )

    reply = await message.reply(
        f"Searching ... <a href='{url}'>\u200b</a>",
        reply_markup=full_keyboard,
    )

    found = False
    if not await common.redis_storage.check_no_found_entry(file_id):
        if results := await find_existing_results(file_id):
            logger.info(f"Found {len(results)} existing results for {url}")
            await asyncio.gather(
                *(send_result(message, result) for result in results),
            )
            found = True
        else:
            logger.info(f"Searching for {url}...")
            async for result in saucenao_search(url, file_id):
                found = True
                await send_result(message, result.provider_result, result.search_provider)

    if not found:
        await common.redis_storage.add_no_found_entry(file_id)
        await reply.edit_text(f"No results found <a href='{url}'>\u200b</a>", reply_markup=full_keyboard)


@form_router.callback_query()
async def callback_a(query: CallbackQuery, state: FSMContext) -> None:
    if query.data in ("A", "B"):
        await query.answer(f"You've chosen {query.data}")


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
