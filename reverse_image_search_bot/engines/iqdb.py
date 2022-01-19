import re

from cachetools import cached
from requests_html import HTMLResponse, HTMLSession
from telegram import InlineKeyboardButton
from yarl import URL

from reverse_image_search_bot.utils import url_button

from .generic import GenericRISEngine
from .types import MetaData, ProviderData


class IQDBEngine(GenericRISEngine):
    name = "IQDB"
    description = "IQDB is a reverse search engine that scrubs ImageBoards for anime/manga related artworks."
    provider_url = URL("https://iqdb.org/")
    types = ["Anime/Manga related Artworks"]
    recommendation = ["Anime/Manga related Artworks"]

    url = "https://iqdb.org/?url={query_url}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = HTMLSession()

    @cached(GenericRISEngine._best_match_cache)
    def best_match(self, url: str | URL) -> ProviderData:
        self.logger.debug("Started looking for %s", url)
        response: HTMLResponse = self.session.get(str(self.get_search_link_by_url(url)))  # type: ignore

        if response.status_code != 200:
            self.logger.debug("Done with search: found nothing")
            return {}, {}

        best_match = response.html.find("table", containing="Best match", first=True)

        if not best_match:
            self.logger.debug("Done with search: found nothing")
            return {}, {}

        result = {}
        meta: MetaData = {}
        buttons: list[InlineKeyboardButton] = []

        rows = best_match.find("td")  # type: ignore
        link = URL(rows[0].find("a", first=True).attrs["href"]).with_scheme("https")  # type: ignore
        if link.host == "danbooru.donmai.us" and (danbooru_id := next(filter(None, reversed(link.parts)), None)):
            result, meta = self._danbooru_provider(int(danbooru_id))
        elif link.host == "yande.re" and (yandere_id := next(filter(None, reversed(link.parts)), None)):
            result, meta = self._yandere_provider(int(yandere_id))
        elif link.host == "gelbooru.com" and (gelbooru_id := link.query.get("id")):
            result, meta = self._gelbooru_provider(int(gelbooru_id))

        buttons = meta.get("buttons", buttons)

        if not result:
            thumbnail = URL(self.url).with_path(rows[0].find("img", first=True).attrs["src"])  # type: ignore
            reg_match = re.match(r"(\d+)×(\d+) \[(\w+)\]", rows[2].text)  # type: ignore
            width, height, rating = reg_match.groups()  # type: ignore

            result = {"Size": f"{width}x{height}", "Rating": rating}
            meta.update({"thumbnail": thumbnail})
            buttons.append(url_button(link))

        meta.update(
            {
                "provider": self.name,
                "provider_url": self.provider_url,
                "buttons": buttons,
                "similarity": int(re.match(r"\d+", rows[3].text)[0]),  # type: ignore
            }
        )

        self.logger.debug("Done with search: found something")
        return self._clean_best_match(result, meta)
