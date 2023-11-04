import asyncio
import logging
import sys
from os import getenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove
from redis.asyncio.client import Redis

form_router = Router()


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

    await message.copy_to(chat_id=message.chat.id)
    await message.reply(
        f"Searching for {message.photo[-1].file_id}...",
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
    TOKEN = getenv("BOT_TOKEN")
    if not TOKEN:
        logging.fatal("BOT_TOKEN env variable is not set")
        sys.exit(1)

    bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=RedisStorage(Redis()))
    dp.include_router(form_router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
