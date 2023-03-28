from asyncio import as_completed, create_task
from pathlib import Path
from tempfile import NamedTemporaryFile, _TemporaryFileWrapper

from aiohttp import ClientSession
from bots import Application
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from reverse_image_search.engines import engines
from reverse_image_search.engines.base import SearchEngine, SearchResponse
from reverse_image_search.utils import chunks


class ReverseImageSearch(Application):
    class Arguments(Application.Arguments):
        pass

    arguments: "ReverseImageSearch.Arguments"

    async def on_initialize(self):
        await super().on_initialize()
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(
            MessageHandler(
                (filters.PHOTO | filters.Document.Category("image/") | filters.Sticker.STATIC)
                & filters.ChatType.PRIVATE,
                self.hndl_image,
            )
        )

        self.session = ClientSession()
        self.engines = [engine(self.session) for engine in engines]

    async def cmd_start(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return

        await update.message.reply_text("Hello")

    async def hndl_image(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        if (
            not update.message
            or not update.effective_chat
            or (not update.message.photo and not update.message.document and not update.message.sticker)
        ):
            return

        applicable_engines = self._get_applicable_engines(update)
        if not applicable_engines:
            await update.message.reply_text("File not supported")
            return

        tg_file = update.message.document or update.message.sticker or update.message.photo[-1]
        get_file = create_task(tg_file.get_file())

        message = await update.message.reply_text("Working on it...")

        result_message: Message | None = None
        with NamedTemporaryFile() as file:
            await (await get_file).download_to_drive(file.name)

            async for response in self._engine_map(applicable_engines, "direct_search_photo", Path(file.name)):
                result_message = await self._send_response(message, response)

        if not result_message:
            await message.edit_text("Nothing found")
        else:
            await message.delete()

    async def _send_response(self, message: Message, response: SearchResponse) -> Message | None:
        buttons = response.buttons
        if response.link:
            buttons.append(InlineKeyboardButton(text="More", url=response.link))

        text = f"{response.engine.name} Search Engine: \n\n{response.text}"

        inline_markup = InlineKeyboardMarkup(list(chunks(buttons, 3)))

        if response.attachment:
            match response.attachment_type:
                case filters._Photo():
                    return await message.reply_photo(
                        response.attachment,
                        caption=text,
                        reply_markup=inline_markup,
                        parse_mode=ParseMode.MARKDOWN_V2,
                    )
                case filters._Video():
                    return await message.reply_video(
                        response.attachment,
                        caption=text,
                        reply_markup=inline_markup,
                        parse_mode=ParseMode.MARKDOWN_V2,
                    )
        else:
            return await message.reply_markdown_v2(text, reply_markup=inline_markup)

    async def _engine_map(self, engines: list[SearchEngine], method: str, file: Path):
        methods = filter(None, [getattr(engine, method) for engine in engines])

        for task in as_completed([method(file) for method in methods]):
            if response := await task:
                yield response

    def _get_applicable_engines(self, update: Update) -> list[SearchEngine]:
        return [engine for engine in self.engines if engine.supports.check_update(update)]
