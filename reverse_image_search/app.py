from pathlib import Path

from aiohttp import ClientSession
from aiostream import stream
from bots import Application
from telegram import Document, InlineKeyboardButton, InlineKeyboardMarkup, Message, PhotoSize, Update, Video
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters
from tgtools.models.file_summary import FileSummary, URLFileSummary
from tgtools.telegram.text import host_emoji, host_name

from reverse_image_search.engines import initiate_engines
from reverse_image_search.engines.saucenao import SauceNaoSearchEngine
from reverse_image_search.providers import initiate_data_providers
from reverse_image_search.providers.base import MessageConstruct
from reverse_image_search.providers.danbooru import DanbooruProvider
from reverse_image_search.utils import chunks, download_file

ZWS = "​"


class ReverseImageSearch(Application):
    class Arguments(Application.Arguments):
        downloads: Path
        file_url: str
        saucenao: SauceNaoSearchEngine.Config
        danbooru: DanbooruProvider.Config

    arguments: "ReverseImageSearch.Arguments"

    async def on_initialize(self):
        await super().on_initialize()
        self.arguments.downloads.mkdir(exist_ok=True, parents=True)

        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(
            MessageHandler(
                filters.PHOTO
                | filters.Sticker.STATIC
                | filters.Sticker.VIDEO
                | filters.VIDEO
                | filters.Document.VIDEO
                | filters.Document.IMAGE
                | filters.ANIMATION,
                self.hndl_search,
            )
        )

        self.session = ClientSession()
        self.providers = await initiate_data_providers(self.session, self.arguments)
        self.engines = await initiate_engines(self.session, self.arguments, self.providers)

    async def cmd_start(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return

        await update.message.reply_text("Hello")

    async def hndl_search(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        # Basically only for nice symbols / please the linter
        if (
            not update.message
            or not update.effective_chat
            or (
                not update.message.photo
                and not update.message.video
                and not update.message.document
                and not update.message.sticker
                and not update.message.animation
            )
        ):
            return

        file = await download_file(update, self.arguments.downloads)
        if not file:
            await update.message.reply_text("Something went wrong, try again or contact the bot author (/help)")
            return

        file_url = self.arguments.file_url + file.name
        file_url = "https://v2.nachtalb.io/ris/f/AQADaL4xGy6R8VF-.jpg"

        buttons = [
            InlineKeyboardButton(engine.name, engine.generate_search_url(str(file_url))) for engine in self.engines
        ]
        buttons = list(chunks(buttons, 3))

        await update.message.reply_text(
            "Use one of the buttons to open the search engine.",
            reply_markup=InlineKeyboardMarkup(buttons),
            reply_to_message_id=update.message.id,
        )

        inline_search_results = stream.merge(*[engine.search(file_url) for engine in self.engines])
        async with inline_search_results.stream() as streamer:
            async for item in streamer:
                if not item:
                    continue
                await self.send_message_construct(item, update.message)

    async def send_message_construct(self, message: MessageConstruct, query_message: Message):
        buttons = [InlineKeyboardButton(f"{host_emoji(message.source_url)} Source", message.source_url)]
        for url in message.additional_urls:
            buttons.append(InlineKeyboardButton(host_name(url, with_emoji=True), url=url))

        buttons = InlineKeyboardMarkup(tuple(chunks(buttons, 3)))

        __import__("ipdb").set_trace()

        if message.file:
            if isinstance(message.file, URLFileSummary) and message.type in [PhotoSize, Video]:
                message.caption += f'\n<a href="{message.file.url}">{ZWS}</a>'
                message.type = None

            file = message.file.file if isinstance(message.file, FileSummary) else message.file.url

            if message.type == PhotoSize:
                return await query_message.reply_photo(
                    file,
                    caption=message.caption,
                    reply_markup=buttons,
                    filename=str(message.file.file_name),
                    parse_mode=ParseMode.HTML,
                )
            elif message.type == Video:
                return await query_message.reply_video(
                    file,
                    caption=message.caption,
                    reply_markup=buttons,
                    filename=str(message.file.file_name),
                    parse_mode=ParseMode.HTML,
                )
            elif message.type == Document:
                return await query_message.reply_document(
                    file,
                    caption=message.caption,
                    reply_markup=buttons,
                    filename=str(message.file.file_name),
                    parse_mode=ParseMode.HTML,
                )
        await query_message.reply_html(message.caption, reply_markup=buttons)