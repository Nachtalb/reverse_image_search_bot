import re

from cachetools import cached
from requests_html import HTMLSession
from telegram import InlineKeyboardButton
from yarl import URL

from .generic import GenericRISEngine


class IQDBEngine(GenericRISEngine):
    name = "IQDB"
    url = "https://iqdb.org/?url={query_url}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = HTMLSession()

    @cached(GenericRISEngine._cache)
    def best_match(self, url: str | URL) -> tuple[dict[str, str | int | URL], list[InlineKeyboardButton]]:
        response = self.session.get(str(self.get_search_link_by_url(url)))

        if response.status_code != 200:
            return {}, []

        best_match = response.html.find("table", containing="Best match", first=True)

        if not best_match:
            return {}, []

        rows = best_match.find("td")

        link = URL(rows[0].find("a", first=True).attrs["href"]).with_scheme("https")
        thumbnail = URL(self.url).with_path(rows[0].find("img", first=True).attrs["src"])
        site_name = rows[1].lxml.xpath("td/text()")[0].strip()

        match = re.match(r"(\d+)×(\d+) \[(\w+)\]", rows[2].text)
        width, height, rating = match.groups()
        width, height = int(width), int(height)

        similarity = re.match(r"\d+%", rows[3].text)[0]

        icon = "📦" if link.host == "danbooru.donmai.us" else "🌐"
        buttons = [InlineKeyboardButton(icon, url=str(link))]

        return {
            "link": link,
            "site name": site_name,
            "thumbnail": thumbnail,
            "size": f"{width}x{height}",
            "width": width,
            "height": height,
            "rating": rating,
            "similarity": similarity,
            "provider": "IQDB",
            "provider url": "https://iqdb.org/",
        }, buttons
