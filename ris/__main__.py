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
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove
from dotenv import load_dotenv
from redis.asyncio.client import Redis

from ris.files import prepare
from ris.s3 import S3Manager
from ris.utils import chunks

load_dotenv()

BASE_URL = getenv("BASE_URL")
if not BASE_URL:
    logging.fatal("BASE_URL env variable is not set")
    sys.exit(1)

form_router = Router()
s3: S3Manager = None  # type: ignore[assignment]

simple_engines = {
    "Google": "https://www.google.com/searchbyimage?safe=off&sbisrc=tg&image_url={file_url}",
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


@form_router.message(Form.search, F.photo)
async def search(message: Message, state: FSMContext) -> None:
    if not message.photo:
        return

    prepared = await prepare(message.photo[-1], message.bot, s3)  # type: ignore[arg-type]
    if not prepared:
        await message.reply("Something went wrong")
        return

    url = f"{BASE_URL}/{prepared}"

    await message.reply(
        f"Searching for {url}...",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=get_simple_engine_buttons(url),
        ),
    )


@form_router.callback_query()
async def callback_a(query: CallbackQuery, state: FSMContext) -> None:
    if query.data in ("A", "B"):
        await query.answer(f"You've chosen {query.data}")


async def main() -> None:
    global s3

    TOKEN = getenv("BOT_TOKEN")
    if not TOKEN:
        logging.fatal("BOT_TOKEN env variable is not set")
        sys.exit(1)

    bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=RedisStorage(Redis()))
    dp.include_router(form_router)

    try:
        s3 = S3Manager(
            access_key=os.environ["S3_ACCESS_KEY"],
            secret_key=os.environ["S3_SECRET_KEY"],
            endpoint_url=os.environ["S3_ENDPOINT_URL"],
            default_bucket=os.environ["S3_DEFAULT_BUCKET"],
        )
    except KeyError as e:
        logging.fatal(f"Missing env variable {e}")
        sys.exit(1)

    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
