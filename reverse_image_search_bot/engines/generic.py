import logging
import random
from typing import TypedDict
from urllib.parse import quote_plus

from cachetools import TTLCache, cached
from telegram import InlineKeyboardButton
from yarl import URL

from reverse_image_search_bot.utils import (
    anilist_info,
    danbooru_info,
    tagify,
    url_button,
)

InternalResultData = dict[str, str | int | URL | None | list[str]]
ResultData = dict[str, str | int | URL]


class MetaData(TypedDict, total=False):
    provider: str
    provider_url: URL
    provided_via: str
    provided_via_url: URL
    thumbnail: URL
    similarity: int | float
    buttons: list[InlineKeyboardButton]


InternalProviderData = tuple[InternalResultData, MetaData]
ProviderData = tuple[ResultData, MetaData]


class GenericRISEngine:
    _cache = TTLCache(maxsize=1e4, ttl=24 * 60 * 60)
    name: str = "GenericRISEngine"
    url: str = ""

    def __init__(self, name: str = None, url: str = None):
        self.name = name or self.name
        self.url = url or self.url
        self.logger = logging.getLogger(f"RISEngine [{self.name}]")

    def __call__(self, url: str | URL, text: str = None) -> InlineKeyboardButton:
        """Create the :obj:`InlineKeyboardButton` button for the telegram but to use"""
        return InlineKeyboardButton(text=text or self.name, url=str(self.get_search_link_by_url(url)))

    def get_search_link_by_url(self, url: str | URL) -> URL:
        """Get the reverse image search link for the given url"""
        return URL(self.url.format(query_url=quote_plus(str(url))))

    def _clean_privider_data(self, data: InternalResultData) -> ResultData:
        for key, value in list(data.items()):
            if value is None or value == "":
                del data[key]
            elif isinstance(value, list):
                data[key] = ", ".join(map(str, value))

        return data  # type: ignore

    def _anilist_provider(self, anilist_id: int, episode_at: int | str = None) -> InternalProviderData:
        ani_data = anilist_info(anilist_id)
        if not ani_data:
            return {}, {}

        episode_at = "?" if episode_at is None else episode_at

        result = {
            "Title": ani_data["title"]["english"],
            "Title [romaji]": ani_data["title"]["romaji"],
            "Episode": f'{episode_at}/{ani_data["episodes"]}',
            "Status": ani_data["status"],
            "Type": ani_data["type"],
            "Year": f"{ani_data['startDate']['year']}-{ani_data['endDate']['year']}",
            "Genres": tagify(ani_data["genres"]),
        }

        meta: MetaData = {
            "provided_via": "AniList",
            "provided_via_url": URL("https://anilist.co/"),
            "thumbnail": URL(ani_data["coverImage"]["large"]),
            "buttons": [url_button(ani_data["siteUrl"])],
        }

        return result, meta

    def _danbooru_provider(self, danbooru_id: int) -> InternalProviderData:
        danbooru_data = danbooru_info(danbooru_id)
        if not danbooru_data:
            return {}, {}

        buttons = []
        if source := danbooru_data.get("source"):
            buttons.append(url_button(source))

        result = {
            "Character": tagify(danbooru_data.get("tag_string_character", [])) or None,
            "Size": f"{danbooru_data['image_width']}x{danbooru_data['image_height']}",
            "Tags": tagify(random.choices(danbooru_data["tag_string_general"].split(" "), k=5)),
            "By": tagify(danbooru_data.get("tag_string_artist", [])) or None,
            "Material": danbooru_data.get("tag_string_copyright", None),
        }

        meta: MetaData = {
            "provided_via": "Danbooru",
            "provided_via_url": URL("https://danbooru.donmai.us/"),
            "thumbnail": URL(danbooru_data["large_file_url"]),  # type: ignore
            "buttons": buttons,
        }

        return result, meta

    @cached(cache=_cache)
    def best_match(self, url: str | URL) -> ProviderData:
        """Get info about the best matching image found

        Returns:
            ProviderData: (
                {  # Everything is optional
                    "Title": "Some Title",
                    "Creator": "Shädman",
                },
                {  # optional fields are marked
                    "thumbnail": URL("https://example.org/image.jpg"),
                    "provider": "SauceNAO",
                    "provider_url": URL("https://saucenao.com/"),
                    "buttons": [InlineKeyboardButton("Source", "https://example.com/")],  # optional
                    "similarity": 85.21,                                # optional: int/float in percentage
                                                                        # some engines don't tell one so it's optional
                    "provided_via": "Danbooru",                         # optional: Data provider (not search engine)
                                                                        # when additional API is used
                    "provided_via_url": "https://danbooru.donmai.us/"   # optional: URL to additional provider
                }
            )
        """
        return {}, {}
