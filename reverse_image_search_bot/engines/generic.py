import logging
from urllib.parse import quote_plus

import httpx
import validators
from cachetools import TTLCache
from telegram import InlineKeyboardButton
from yarl import URL

from reverse_image_search_bot.utils.async_cache import async_cached

from .types import InternalResultData, MetaData, ProviderData, ResultData

__all__ = ["GenericRISEngine", "PreWorkEngine"]


class GenericRISEngine:
    _best_match_cache = TTLCache(maxsize=1e4, ttl=24 * 60 * 60)
    name: str = "GenericRISEngine"
    description: str = ""
    provider_url: URL = URL()
    types: list[str] = []
    recommendation: list[str] = []

    url: str = ""

    def __init__(
        self,
        name: str | None = None,
        url: str | None = None,
        description: str = "",
        provider_url: str | URL = "",
        types: list[str] | None = None,
        recommendation: list[str] | None = None,
    ):
        self.name = name or self.name
        self.description = description or self.description
        self.provider_url = URL(provider_url) or self.provider_url
        self.types = types or self.types
        self.recommendation = recommendation or self.recommendation

        self.url = url or self.url

        self.logger = logging.getLogger(f"RISEngine [{self.name}]")

    def __call__(self, url: str | URL, text: str | None = None) -> InlineKeyboardButton:
        """Create the :obj:`InlineKeyboardButton` button for the telegram bot to use"""
        search_url = self.get_search_link_by_url(url) or ""
        return InlineKeyboardButton(text=text or self.name, url=search_url)

    def get_search_link_by_url(self, url: str | URL) -> str | None:
        """Get the reverse image search link for the given url"""
        return self.url.format(query_url=quote_plus(str(url)))

    def _clean_privider_data(self, data: InternalResultData) -> ResultData:
        for key, value in list(data.items()):
            if value is None or value == "":
                del data[key]

        return data  # type: ignore

    def _clean_meta_data(self, data: MetaData) -> MetaData:
        for button in data.get("buttons", [])[:]:
            if button.url and not validators.url(button.url):
                data["buttons"].remove(button)
        return data

    def _clean_best_match(self, result: InternalResultData, meta: MetaData) -> tuple[ResultData, MetaData]:
        return self._clean_privider_data(result), self._clean_meta_data(meta)

    @classmethod
    @property
    def best_match_implemented(cls):
        return "best_match" in cls.__dict__ and cls is not GenericRISEngine

    @async_cached(cache=_best_match_cache)
    async def best_match(self, url: str | URL) -> ProviderData:
        """Get info about the best matching image found

        Returns:
            ProviderData: (result_dict, meta_dict)
        """
        raise NotImplementedError()


class PreWorkEngine(GenericRISEngine):
    url: str = ""
    pre_url: str = ""
    _url_cache = TTLCache(1e4, ttl=24 * 60 * 60)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._http_client = httpx.AsyncClient(timeout=10)

    @async_cached(_url_cache)
    async def __call__(self, url: str | URL, text: str | None = None) -> InlineKeyboardButton | None:
        search_url = await self._resolve_search_url(url)
        if not search_url:
            return None
        return InlineKeyboardButton(text=text or self.name, url=search_url)

    async def _resolve_search_url(self, url: str | URL) -> str | None:
        raise NotImplementedError()

    def empty_button(self):
        return InlineKeyboardButton(text="⌛ " + self.name, callback_data=f"wait_for {self.name}")
