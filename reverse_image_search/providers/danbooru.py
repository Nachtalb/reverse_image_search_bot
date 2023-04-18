from random import choices
from typing import Any

from aiohttp import ClientSession
from emoji import emojize
from pydantic import BaseModel
from tgtools.api.danbooru import DanbooruApi
from tgtools.models.danbooru import RATING
from tgtools.telegram.text import tagify
from yarl import URL

from .base import Info, MessageConstruct, Provider


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

        text: dict[str, str | Info] = {
            "Rating": "",
            "Artist": ", ".join(tagify(post.tags_artist)),
            "Tags": ", ".join(tagify(choices(list(post.tags), k=10))),
            "Characters": ", ".join(tagify(post.tags_character)),
            "Copyright": ", ".join(tagify(post.tags_copyright)),
        }
        if post.rating:
            rating_emoji = emojize(":no_one_under_eighteen:" if RATING.level(post.rating) > 1 else ":cherry_blossom:")
            text["Rating"] = Info(f"{rating_emoji} {post.rating_simple}", "code")

        source = f"https://www.pixiv.net/artworks/{post.pixiv_id}" if post.pixiv_id else post.source

        return MessageConstruct(
            source_url=source or post.url,
            additional_urls=[] if not post.source else [post.url],
            file=post.file_summary,
            text=text,
        )
