import logging
from urllib.parse import quote_plus

from cachetools import TTLCache, cached
from telegram import InlineKeyboardButton
from yarl import URL

from .providers import ProviderCollection
from .types import InternalResultData, ProviderData, ResultData


__all__ = ["GenericRISEngine"]


class GenericRISEngine(ProviderCollection):
    _best_match_cache = TTLCache(maxsize=1e4, ttl=24 * 60 * 60)
    name: str = "GenericRISEngine"
    url: str = ""

    def __init__(self, name: str = None, url: str = None):
        self.name = name or self.name
        self.url = url or self.url
        self.logger = logging.getLogger(f"RISEngine [{self.name}]")

    def __call__(self, url: str | URL, text: str = None) -> InlineKeyboardButton | None:
        """Create the :obj:`InlineKeyboardButton` button for the telegram but to use"""
        search_url = self.get_search_link_by_url(url)
        if not search_url:
            return
        return InlineKeyboardButton(text=text or self.name, url=str(search_url))

    def get_search_link_by_url(self, url: str | URL) -> URL | None:
        """Get the reverse image search link for the given url"""
        return URL(self.url.format(query_url=quote_plus(str(url))))

    def _clean_privider_data(self, data: InternalResultData) -> ResultData:
        for key, value in list(data.items()):
            if value is None or value == "":
                del data[key]
            elif isinstance(value, list):
                data[key] = ", ".join(map(str, value))

        return data  # type: ignore

    @cached(cache=_best_match_cache)
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
                    "identifier": "something"                           # optional: identifier to prevent search results from other engines (text only)
                    "thumbnail_identifier": "something"                 # optional: identifier to prevent search results from other engines (thumbnail only)
                }
            )
        """
        raise NotImplementedError()
