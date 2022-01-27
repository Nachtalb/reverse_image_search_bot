from datetime import datetime
from urllib.parse import quote_plus

from cachetools import cached
from requests import Session
from telegram import InlineKeyboardButton
from telegram.ext import CallbackContext
from yarl import URL

from reverse_image_search_bot import settings
from reverse_image_search_bot.utils import url_button

from .data_providers import anilist
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
        self.session = Session()

    @property
    def use_api_key(self):
        return self._use_api_key

    @use_api_key.setter
    def use_api_key(self, value):
        from reverse_image_search_bot.bot import job_queue  # import it now to not get import recursion during boot

        self._use_api_key = value

        job_name = "trace_api"
        if value and not job_queue.get_jobs_by_name(job_name):
            job_queue.run_monthly(self._stop_using_api_key, when=datetime.min.time(), day=1, name=job_name)

    def _stop_using_api_key(self, _: CallbackContext):
        self._use_api_key = False

    def _fetch_data(self, url: URL | str) -> int | dict:
        api_link = "https://api.trace.moe/search"
        params = {"url": str(url)}

        result = None
        if not self.use_api_key:
            result = self.session.get(api_link, params=params)

        if self.use_api_key or (result is not None and result.status_code == 402):
            self.use_api_key = True
            headers = {"x-trace-key": settings.TRACE_API}
            result = self.session.get(api_link, params=params, headers=headers)

        if result and result.status_code != 200:
            return result.status_code
        else:
            return result.json() if result else {}

    @cached(GenericRISEngine._best_match_cache)
    def best_match(self, url: str | URL) -> ProviderData:
        self.logger.debug("Started looking for %s", url)

        meta: MetaData = {
            "provider": self.name,
            "provider_url": self.provider_url,
        }
        limit_reached_result = "Monthly limit reached. You can search Trace via it's button above or <b>More</b> below."

        data = self._fetch_data(url)

        if data == 402:
            meta["errors"] = [limit_reached_result]
            return {}, meta
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

        result, meta = anilist.provide(int(anilist_id), data["episode"])

        if meta:
            buttons = meta.get("buttons", [])

        if not result:
            titles = {}
            if isinstance(data["anilist"], int):
                buttons.append(url_button("https://anilist.co/anime/%d" % data["anilist"]))
            else:
                anilist_data = data["anilist"]
                titles = anilist_data["titles"]
                buttons.append(url_button("https://anilist.co/anime/%d" % anilist_data["id"]))
                buttons.append(url_button("https://myanimelist.net/anime/%d" % anilist_data["idMal"]))

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

        self.logger.debug("Done with search: found something")
        return self._clean_best_match(result, meta)
