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
    url = "https://iqdb.org/?url={query_url}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = HTMLSession()

    @cached(GenericRISEngine._cache)
    def best_match(self, url: str | URL) -> ProviderData:
        response: HTMLResponse = self.session.get(str(self.get_search_link_by_url(url)))  # type: ignore

        if response.status_code != 200:
            return {}, {}

        best_match = response.html.find("table", containing="Best match", first=True)

        if not best_match:
            return {}, {}

        result = {}
        meta: MetaData = {}
        buttons: list[InlineKeyboardButton] = []

        rows = best_match.find("td")  # type: ignore
        link = URL(rows[0].find("a", first=True).attrs["href"]).with_scheme("https")  # type: ignore
        if link.host == "danbooru.donmai.us" and (danbooru_id := next(filter(None, reversed(link.parts)), None)):
            result, meta = self._danbooru_provider(int(danbooru_id))
            buttons = meta.get("buttons", [])

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
                "provider_url": URL("https://iqdb.org/"),
                "buttons": buttons,
                "similarity": int(re.match(r"\d+", rows[3].text)[0]),  # type: ignore
            }
        )

        result = self._clean_privider_data(result)

        return result, meta
