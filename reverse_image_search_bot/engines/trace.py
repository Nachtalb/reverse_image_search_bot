from datetime import datetime

import httpx
from telegram import InlineKeyboardButton
from telegram.ext import ContextTypes
from yarl import URL

from reverse_image_search_bot import settings
from reverse_image_search_bot.utils import url_button
from reverse_image_search_bot.utils.async_cache import async_cached

from .data_providers import anilist
from .errors import RateLimitError
from .generic import GenericRISEngine
from .types import MetaData, ProviderData


class TraceEngine(GenericRISEngine):
    name = "Trace"
    description = "Search Anime by screenshots. Lookup the exact moment and the episode."
    provider_url = URL("https://trace.moe/")
    types = ["Anime"]
    recommendation = ["Anime"]

    url = "https://trace.moe/?auto&url={query_url}"
    _use_api_key = False

    min_similarity = 91

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._http_client = httpx.AsyncClient(timeout=10)

    @property
    def use_api_key(self):
        return self._use_api_key

    @use_api_key.setter
    def use_api_key(self, value):
        from reverse_image_search_bot.bot import application

        self._use_api_key = value

        if value and application and application.job_queue:
            job_name = "trace_api"
            if not application.job_queue.get_jobs_by_name(job_name):
                application.job_queue.run_monthly(
                    self._stop_using_api_key, when=datetime.min.time(), day=1, name=job_name
                )

    async def _stop_using_api_key(self, context: ContextTypes.DEFAULT_TYPE):
        self._use_api_key = False

    async def _fetch_data(self, url: URL | str) -> int | dict:
        api_link = "https://api.trace.moe/search"
        params = {"url": str(url)}

        result = None
        if not self.use_api_key:
            result = await self._http_client.get(api_link, params=params, timeout=5)

        if self.use_api_key or (result is not None and result.status_code == 402):
            self.use_api_key = True
            headers = {"x-trace-key": settings.TRACE_API}
            result = await self._http_client.get(api_link, params=params, headers=headers, timeout=5)

        if result and result.status_code != 200:
            return result.status_code
        else:
            return result.json() if result else {}

    @async_cached(GenericRISEngine._best_match_cache)
    async def best_match(self, url: str | URL) -> ProviderData:
        self.logger.debug("Started looking for %s", url)

        meta: MetaData = {
            "provider": self.name,
            "provider_url": self.provider_url,
        }
        data = await self._fetch_data(url)

        if data == 402:
            raise RateLimitError("Trace 402 monthly limit", period="Monthly")
        elif isinstance(data, int) or not data:
            self.logger.debug("Done with search: found nothing")
            return {}, {}

        data = next(iter(data["result"]), None)
        if not data or data["similarity"] < (self.min_similarity / 100):
            self.logger.debug("Done with search: found nothing")
            return {}, {}

        buttons: list[InlineKeyboardButton] = []
        result = {}

        anilist_id = data["anilist"]
        if isinstance(data["anilist"], dict):
            anilist_id = data["anilist"]["id"]

        result, meta = await anilist.provide(int(anilist_id), data["episode"])

        if meta:
            buttons = meta.get("buttons", [])

        if not result:
            titles = {}
            if isinstance(data["anilist"], int):
                buttons.append(url_button(f"https://anilist.co/anime/{data['anilist']}"))
            else:
                anilist_data = data["anilist"]
                titles = anilist_data["titles"]
                buttons.append(url_button(f"https://anilist.co/anime/{anilist_data['id']}"))
                buttons.append(url_button(f"https://myanimelist.net/anime/{anilist_data['idMal']}"))

            result.update(
                {
                    "Title": titles.get("english"),
                    "Title [romaji]": titles.get("romaji"),
                    "Episode": data["episode"],
                    "Filename": data["filename"],
                }
            )

        if "from" in data and "to" in data:
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

        self.logger.debug("Done with search: found something")
        return self._clean_best_match(result, meta)
