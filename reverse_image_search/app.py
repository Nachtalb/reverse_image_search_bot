from bots import Application
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters


class ReverseImageSearch(Application):
    class Arguments(Application.Arguments):
        pass

    arguments: "ReverseImageSearch.Arguments"

    async def on_initialize(self):
        await super().on_initialize()
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, self.hndl_image))

    async def cmd_start(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return

        await update.message.reply_text("Hello")

    async def hndl_image(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.effective_chat:
            return

        await update.message.copy(update.effective_chat.id)
