from datetime import datetime
from urllib.parse import quote_plus

from cachetools import cached
from requests import Session
from telegram import InlineKeyboardButton
from yarl import URL

from reverse_image_search_bot.utils import url_button

from .generic import GenericRISEngine
from .types import MetaData, ProviderData


class TraceEngine(GenericRISEngine):
    name = "Trace"
    url = "https://trace.moe/?auto&url={query_url}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = Session()

    @cached(GenericRISEngine._best_match_cache)
    def best_match(self, url: str | URL) -> ProviderData:
        api_link = "https://api.trace.moe/search?url={}".format(quote_plus(str(url)))
        response = self.session.get(api_link)

        if response.status_code != 200:
            return {}, {}

        data = next(iter(response.json()["result"]), None)
        if not data or data["similarity"] < 0.9:
            return {}, {}

        buttons: list[InlineKeyboardButton] = []
        result = {}
        meta: MetaData = {}

        anilist_id = data["anilist"]
        if isinstance(data["anilist"], dict):
            anilist_id = data["anilist"]["id"]

        result, meta = self._anilist_provider(int(anilist_id), data["episode"])

        if meta:
            buttons = meta.get("buttons", [])

        if not result:
            titles = {}
            if isinstance(data["anilist"], int):
                buttons.append(url_button("https://anilist.co/anime/%d" % data["anilist"]))
            else:
                anilist = data["anilist"]
                titles = anilist["titles"]
                buttons.append(url_button("https://anilist.co/anime/%d" % anilist["id"]))
                buttons.append(url_button("https://myanimelist.net/anime/%d" % anilist["idMal"]))

            result.update(
                {
                    "Title": titles.get("english"),
                    "Title [romaji]": titles.get("romaji"),
                    "Episode": data["episode"],
                    "Filename": data["filename"],
                }
            )

        from_t = datetime.fromtimestamp(data["from"]).strftime("%H:%M:%S")
        to_t = datetime.fromtimestamp(data["to"]).strftime("%H:%M:%S")
        result.update(
            {
                "Est. Time": f"{from_t} / {to_t}",
            }
        )

        meta.update(
            {
                "thumbnail": URL(data["video"]),
                "provider": self.name,
                "provider_url": URL("https://trace.moe/"),
                "similarity": round(data["similarity"] * 100, 2),
                "buttons": buttons,
                "thumbnail_identifier": data["video"],
            }
        )

        result = self._clean_privider_data(result)

        return result, meta
