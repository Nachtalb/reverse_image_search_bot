from urllib.parse import quote_plus

from cachetools import cached
from requests import Session
from telegram import InlineKeyboardButton
from yarl import URL

from .generic import GenericRISEngine


class TraceEngine(GenericRISEngine):
    name = "Trace"
    url = "https://trace.moe/?auto&url={query_url}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = Session()

    @cached(GenericRISEngine._cache)
    def best_match(self, url: str | URL) -> tuple[dict[str, str | int | URL], list[InlineKeyboardButton]]:
        api_link = "https://api.trace.moe/search?url={}".format(quote_plus(str(url)))
        response = self.session.get(api_link)

        if response.status_code != 200:
            return {}, []

        data = next(iter(response.json()["result"]), None)
        if not data or data["similarity"] < 0.9:
            return {}, []

        buttons = []

        anilist, anilist_link, is_adult, mal_link = {}, None, None, None
        if isinstance(data["anilist"], int):
            anilist_link = URL("https://anilist.co/anime/%d" % data["anilist"])
            buttons.append(InlineKeyboardButton(text="AniList", url=str(anilist_link)))
        else:
            anilist = data["anilist"]

            is_adult = "Yes" if anilist["isAdult"] else "No"
            anilist_link = URL("https://anilist.co/anime/%d" % anilist["id"])
            mal_link = URL("https://myanimelist.net/anime/%d" % anilist["idMal"])
            buttons.append(InlineKeyboardButton(text="AniList", url=str(anilist_link)))
            buttons.append(InlineKeyboardButton(text="MAL", url=str(mal_link)))

        result_data = {
            "link": anilist_link,
            "mal link": mal_link,
            "file name": data["filename"],
            "thumbnail": URL(data["video"]),
            "image": URL(data["image"]),
            "title romaji": anilist.get("title", {}).get("romaji"),
            "title english": anilist.get("title", {}).get("english"),
            "title native": anilist.get("title", {}).get("native"),
            "synonyms": ", ".join(anilist.get("synonyms", [])) or None,
            "episode": data["episode"],
            "from": data["from"],
            "to": data["to"],
            "is adult": is_adult,
            "similarity": data["similarity"],
            "provider": self.name,
            "provider url": "https://trace.moe/",
        }

        for key, value in list(result_data.items()):
            if value is None:
                del result_data[key]

        return result_data, buttons
