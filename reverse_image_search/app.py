from asyncio import create_task, gather
from pathlib import Path
from typing import Sequence, Tuple

from aiohttp import ClientSession
from aiostream import stream
from bots import Application
from telegram import (
    Animation,
    Document,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaAnimation,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
    PhotoSize,
    Update,
    Video,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters
from tgtools.telegram.compatibility import OutputFileType, make_tg_compatible
from tgtools.utils.types import TELEGRAM_FILES
from tgtools.utils.urls.emoji import FALLBACK_EMOJIS, host_name

from reverse_image_search.engines import initiate_engines
from reverse_image_search.engines.saucenao import SauceNaoSearchEngine
from reverse_image_search.providers import initiate_data_providers
from reverse_image_search.providers.base import SearchResult
from reverse_image_search.providers.booru import BooruProvider
from reverse_image_search.providers.pixiv import PixivProvider
from reverse_image_search.utils import chunks, download_file

ZWS = "​"

SUPPORTED_MEDIA = InputMediaPhoto | InputMediaVideo | InputMediaAnimation | InputMediaDocument


class ReverseImageSearch(Application):
    class Arguments(Application.Arguments):
        downloads: Path
        file_url: str
        saucenao: SauceNaoSearchEngine.Config
        boorus: BooruProvider.Config
        pixiv: PixivProvider.Config

    arguments: "ReverseImageSearch.Arguments"

    async def on_initialize(self) -> None:
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

    async def cmd_start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        await update.message.reply_text("Hello")

    async def hndl_search(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
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
        file_url = "https://v2.nachtalb.io/ris/f/AQADWb0xG1lWQVF-.jpg"

        buttons = [
            InlineKeyboardButton(engine.name, engine.generate_search_url(str(file_url))) for engine in self.engines
        ]

        await update.message.reply_text(
            "Use one of the buttons to open the search engine.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Open Image", url=file_url)]] + list(chunks(buttons, 3))
            ),
            reply_to_message_id=update.message.id,
        )

        inline_search_results = stream.merge(*[engine.search(file_url) for engine in self.engines])
        async with inline_search_results.stream() as streamer:
            async for result in streamer:
                if not result or result.message is None:
                    continue
                try:
                    await self.send_message_construct(result, update.message)
                except BadRequest:
                    await self.send_message_construct(result, update.message, force_download=True)

    async def send_message_construct(
        self, result: SearchResult, query_message: Message, force_download: bool = False
    ) -> None:
        buttons = [
            InlineKeyboardButton(
                host_name(result.message.provider_url, with_emoji=True, fallback=FALLBACK_EMOJIS["globe"]),
                result.message.provider_url,
            )
        ]
        for url in result.message.additional_urls:
            buttons.append(InlineKeyboardButton(host_name(url, with_emoji=True), url=url))

        markup = InlineKeyboardMarkup(tuple(chunks(buttons, 3)))

        additional_files_tasks = [
            create_task(make_tg_compatible(file=file, force_download=force_download))
            for file in result.message.additional_files
        ]
        main_summary = None
        type_: TELEGRAM_FILES = Document
        if result.message.file:
            main_summary, type_ = await make_tg_compatible(file=result.message.file, force_download=force_download)

        # Send main file for the message
        if main_summary:
            result.message.file = main_summary
            common_file = await main_summary.as_common()  #  pyright: ignore

            if type_ is PhotoSize:
                main_message = await query_message.reply_photo(
                    photo=common_file, caption=result.caption, parse_mode=ParseMode.HTML, reply_markup=markup
                )
            elif type_ is Video:
                main_message = await query_message.reply_video(
                    video=common_file, caption=result.caption, parse_mode=ParseMode.HTML, reply_markup=markup
                )
            elif type_ is Animation:
                main_message = await query_message.reply_animation(
                    animation=common_file, caption=result.caption, parse_mode=ParseMode.HTML, reply_markup=markup
                )
            else:
                main_message = await query_message.reply_document(
                    document=common_file, caption=result.caption, parse_mode=ParseMode.HTML, reply_markup=markup
                )
        else:
            main_message = await query_message.reply_html(
                text=result.caption,
                reply_markup=markup,
            )

        # Send additional files if needed
        if additional_files_tasks:
            ready_files = [(file, type_) for file, type_ in await gather(*additional_files_tasks) if file is not None]

            await self._send_media_group(
                files=ready_files,
                message=main_message,
                captions=result.message.additional_files_captions,
            )

    async def _get_input_media(
        self,
        file: OutputFileType,
        type_: TELEGRAM_FILES,
        caption: str | None = None,
        parse_mode: str = ParseMode.HTML,
        no_animation: bool = False,
    ) -> SUPPORTED_MEDIA:
        """
        Get the respective `InputMedia` for the given file.

        Args:
            file (OutputFileType): A file like that can be used for telegram
            type_ (TELEGRAM_FILES): What telegram equal it is PhotoSize, Video, Animation or Document
            caption (str, optional): An additional caption for this piece of media.
            parse_mode (str, optional): What parse mode to use for the caption (defaults to HTML)
            no_animation (bool, optional): Wether to use Video for Animations. As not all functions support Animation.
                (defaults to False)

        Returns:
            The corresponding `InputMedia[file type]`
        """
        common_format = await file.as_common()
        if type_ is PhotoSize:
            return InputMediaPhoto(media=common_format, caption=caption, parse_mode=parse_mode)
        elif type_ is Video or (no_animation and type_ is Animation):
            return InputMediaVideo(media=common_format, caption=caption, parse_mode=parse_mode)
        elif type_ is Animation:
            return InputMediaAnimation(media=common_format, caption=caption, parse_mode=parse_mode)
        else:
            return InputMediaDocument(media=common_format, caption=caption, parse_mode=parse_mode)

    async def _send_media_group(
        self,
        files: Sequence[Tuple[OutputFileType, TELEGRAM_FILES]],
        message: Message,
        captions: Sequence[str | None] | str | None = None,
    ) -> tuple[Message, ...] | None:
        """
        Send a group of file as reply to a message

        Args:
            files (Sequence[tuple[OutputFileType, TELEGRAM_FILES]]]): The additional files already made compatible
                with Telegram
            message (Message): The message that the group should reply to.
            captions (Sequence[str | None] | str, optional): A list of captions or a single caption for the media
                group files in HTML format
            force_download (bool, optional): If we want to enforce downloading the files first (defaults to False).

        Returns:
            A tuple of all Messages in the MediaGroup or None if the files were empty or not Telegram compatible.
        """
        clean_captions: Sequence[str | None] = []
        if isinstance(captions, str):
            clean_captions = [captions] + [None] * (len(files) - 1)
        elif captions is None:
            clean_captions = [None] * len(files)
        else:
            clean_captions = captions

        ready_media = []
        for (file, type_), caption in zip(files, clean_captions):
            if not file:
                continue
            ready_media.append(
                await self._get_input_media(
                    file=file,
                    type_=type_,
                    caption=caption,
                    no_animation=True,
                )
            )

        if not ready_media:
            return None

        return await message.reply_media_group(media=ready_media)
