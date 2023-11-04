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

load_dotenv()

BASE_URL = getenv("BASE_URL")
if not BASE_URL:
    logging.fatal("BASE_URL env variable is not set")
    sys.exit(1)

form_router = Router()
s3: S3Manager = None  # type: ignore[assignment]


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

    await message.copy_to(chat_id=message.chat.id)
    await message.reply(
        f"Searching for {url}...",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="A", callback_data="A"),
                    InlineKeyboardButton(text="B", callback_data="B"),
                ]
            ],
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
