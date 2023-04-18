from typing import Any

from aiohttp import ClientSession
from emoji import emojize
from pydantic import BaseModel
from tgtools.api.danbooru import DanbooruApi
from tgtools.models.danbooru import RATING
from tgtools.telegram.text import tagified_string
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
        id_ = data.get("danbooru_id")
        if not id_:
            return
        post = await self.api.post(id_)
        if not post:
            return

        text: dict[str, str | Info] = {
            "Rating": "",
            "Artist": tagified_string(post.tags_artist),
            "Tags": tagified_string(post.tags, 10),
            "Characters": tagified_string(post.tags_character),
            "Copyright": tagified_string(post.tags_copyright),
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
