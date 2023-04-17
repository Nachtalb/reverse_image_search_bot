from random import choices
from typing import Any

from aiohttp import ClientSession
from emoji import emojize
from pydantic import BaseModel
from telegram import Document, PhotoSize, Video
from tgtools.api.danbooru import DanbooruApi
from tgtools.models.danbooru import RATING
from tgtools.telegram.compatibility import make_tg_compatible
from tgtools.telegram.text import tagify
from yarl import URL

from .base import MessageConstruct, Provider


class DanbooruProvider(Provider):
    base_url = URL("https://danbooru.donmai.us")

    class Config(BaseModel):
        api_key: str
        username: str

    def __init__(self, session: ClientSession, api_key: str, username: str) -> None:
        self.api = DanbooruApi(session, username, api_key)

    async def provide(self, data: dict[str, Any]) -> MessageConstruct | None:
        if "id" not in data:
            return
        post = await self.api.post(data["id"])
        if not post:
            return

        caption = ""
        if post.rating:
            rating_emoji = emojize(":no_one_under_eighteen:" if RATING.level(post.rating) > 1 else ":cherry_blossom:")
            caption += f"Rating: {rating_emoji} <code>{post.rating_simple}</code>\n"
        if post.tags_artist:
            caption += f"Artist: {', '.join(tagify(post.tags_artist))}\n"
        if post.tags:
            caption += f"Tags: {', '.join(tagify(choices(list(post.tags), k=10)))}\n"
        if post.tags_character:
            caption += f"Characters: {', '.join(tagify(post.tags_character))}\n"
        if post.tags_copyright:
            caption += f"Copyright: {', '.join(tagify(post.tags_copyright))}"

        summary, as_document = await make_tg_compatible(post.file_summary)

        type_ = None
        if summary:
            type_ = Document if as_document else PhotoSize if summary.is_image else Video

        source = f"https://www.pixiv.net/artworks/{post.pixiv_id}" if post.pixiv_id else post.source

        return MessageConstruct(
            type=type_,
            caption=caption,
            source_url=source or post.url,
            additional_urls=[] if not post.source else [post.url],
            file=summary,
        )
