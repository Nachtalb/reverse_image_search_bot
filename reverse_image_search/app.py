from pathlib import Path

from bots import Application
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters
from yarl import URL

from reverse_image_search.engines import engines
from reverse_image_search.utils import chunks, download_file


class ReverseImageSearch(Application):
    class Arguments(Application.Arguments):
        downloads: Path
        file_url: str

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

        self.engines = engines

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

        buttons = [
            InlineKeyboardButton(engine.name, engine.generate_search_url(str(file_url))) for engine in self.engines
        ]
        buttons = list(chunks(buttons, 3))

        await update.message.reply_text(
            "Use one of the buttons to open the search engine.",
            reply_markup=InlineKeyboardMarkup(buttons),
            reply_to_message_id=update.message.id,
        )
