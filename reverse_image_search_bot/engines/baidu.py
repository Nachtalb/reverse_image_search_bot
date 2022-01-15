from urllib.parse import quote_plus

from cachetools import TTLCache, cached
from requests import Session
from yarl import URL

from .generic import GenericRISEngine


class BaiduEngine(GenericRISEngine):
    name = "Baidu"
    url = "https://graph.baidu.com/upload?image={query_url}&from=pc"
    _cache = TTLCache(maxsize=1e4, ttl=24 * 60 * 60)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = Session()

    @cached(_cache)
    def get_search_link_by_url(self, url: str | URL) -> URL | None:
        pre_url = self.url.format(query_url=quote_plus(str(url)))

        response = self.session.get(pre_url)
        if response.status_code != 200:
            return

        search_url = response.json().get("data", {}).get("url")
        return URL(search_url) if search_url else None
