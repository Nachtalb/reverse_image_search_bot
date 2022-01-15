from threading import Lock
from time import time
from urllib.parse import quote_plus

from cachetools import cached
from requests import Session
from telegram import InlineKeyboardButton
from yarl import URL

from reverse_image_search_bot.settings import SAUCENAO_API
from reverse_image_search_bot.utils import tagify, url_button

from .generic import GenericRISEngine
from .types import InternalProviderData, MetaData, ProviderData


class SauceNaoEngine(GenericRISEngine):
    name = "SauceNAO"
    url = "https://saucenao.com/search.php?url={query_url}"
    limit_reached = None

    ResponseData = dict[str, str | int | list[str]]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = Session()
        self.lock = Lock()

    def _21_provider(self, data: ResponseData) -> InternalProviderData:
        """Anime"""
        buttons: list[InlineKeyboardButton] = []

        meta: MetaData = {}
        result = {}
        if "anilist_id" in data:
            result, meta = self._anilist_provider(data["anilist_id"], data.get("part"))  # type: ignore
            if result:
                buttons = meta.get("buttons", [])
                for item in data.get("ext_urls", []):  # type: ignore
                    if "anilist.co" not in item:
                        buttons.append(url_button(item))

        if not result:
            for item in data.get("ext_urls", []):  # type: ignore
                buttons.append(url_button(item))

            result.update(
                {
                    "Source": data["source"],
                    "Episode": data["part"],
                }
            )

        result.update(
            {
                "Year": data["year"],
                "Est. Time": data["est_time"],
            }
        )

        meta["buttons"] = buttons
        return result, meta

    def _5_provider(self, data: ResponseData) -> InternalProviderData:
        """Pixiv"""
        return (
            {"Title": data["title"], "Creator": data["member_name"]},
            {
                "buttons": [
                    url_button(f"https://www.pixiv.net/en/artworks/{data['pixiv_id']}", text="Source"),
                    url_button(f"https://www.pixiv.net/en/users/{data['member_id']}", text="Artist"),
                ]
            },
        )

    def _9_provider(self, data: ResponseData) -> InternalProviderData:
        """Danbooru"""
        buttons: list[InlineKeyboardButton] = []
        result = {}
        meta: MetaData = {}

        if "danbooru_id" in data:
            result, meta = self._danbooru_provider(data["danbooru_id"])  # type: ignore
            if meta:
                buttons = meta.get("buttons", [])

        if not result:
            if source := data.get("source"):
                buttons.append(url_button(source, text="Source"))  # type: ignore

            for item in data.get("ext_urls", []):  # type: ignore
                buttons.append(url_button(item))

            result.update(
                {
                    "Character": tagify(data.get("characters")),  # type: ignore
                    "Material": data.get("material"),
                    "By": tagify(data.get("creator")),  # type: ignore
                }
            )

        meta["buttons"] = buttons
        return result, meta

    def _default_provider(self, data: ResponseData) -> InternalProviderData:
        """Generic"""
        buttons: list[InlineKeyboardButton] = []
        for item in data.pop("ext_urls", []):  # type: ignore
            buttons.append(url_button(item))

        result = {}
        meta = {"buttons": buttons}

        for key, value in list(data.items()):
            match key:
                case k if k.endswith(("_id", "_aid")):
                    continue
                case "twitter_user_handle":
                    result["Poster"] = value.title()  # type: ignore
                    buttons.append(url_button(f"https://twitter.com/{value}", text=value.title()))  # type: ignore
                case _:
                    result[key.replace("_", " ").title()] = value

        return result, meta  # type: ignore

    @cached(GenericRISEngine._cache)
    def best_match(self, url: str | URL) -> ProviderData:
        meta: MetaData = {
            "provider": self.name,
            "provider_url": URL("https://saucenao.com/"),
        }
        limit_reached_result = {"Daily limit reached": 'Please click the "More" button below'}

        if self.limit_reached and time() - self.limit_reached < 3600:
            return limit_reached_result, meta  # type: ignore

        api_link = "https://saucenao.com/search.php?db=999&output_type=2&testmode=1&numres=8&url={}{}".format(
            quote_plus(str(url)), f"&api_key={SAUCENAO_API}" if SAUCENAO_API else ""
        )
        with self.lock:
            response = self.session.get(api_link)

        if response.status_code == 429:
            self.limit_reached = time()
            return limit_reached_result, meta  # type: ignore

        if response.status_code != 200:
            return {}, {}

        results = filter(lambda d: float(d["header"]["similarity"]) >= 60, response.json().get("results", []))

        priority = 21, 5, 9  # Anime, Pixiv, Danbooru
        data = next(
            iter(
                sorted(
                    results,
                    key=lambda r: (
                        priority.index(r["header"]["index_id"]) if r["header"]["index_id"] in priority else 99,
                        float(r["header"]["similarity"]) * -1,
                    ),
                )
            ),
            None,
        )

        if not data:
            return {}, {}

        data_provider = getattr(self, f"_{data['header']['index_id']}_provider", self._default_provider)
        result, new_meta = data_provider(data["data"])
        meta.update(new_meta)

        meta.update(
            {
                "thumbnail": URL(meta.get("thumbnail", data["header"]["thumbnail"])),
                "similarity": float(data["header"]["similarity"]),
            }
        )

        return self._clean_privider_data(result), meta
