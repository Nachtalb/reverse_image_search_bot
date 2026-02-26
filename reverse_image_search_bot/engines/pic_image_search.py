"""
Generic base engine for PicImageSearch-backed engines.
Each subclass sets `pic_engine_class` and optionally overrides `_extract`.
"""
import asyncio

from cachetools import cached
from yarl import URL

from reverse_image_search_bot.utils.url import url_button

from .generic import GenericRISEngine
from .types import InternalProviderData, MetaData, ProviderData

__all__ = ["PicImageSearchEngine"]


class PicImageSearchEngine(GenericRISEngine):
    """Base class for engines backed by the PicImageSearch library.

    Subclasses must set:
        pic_engine_class: the PicImageSearch engine class to use

    Subclasses may override:
        _extract(raw): map raw result list → (result_dict, meta_dict)
    """

    pic_engine_class = None  # e.g. PicImageSearch.Yandex

    @classmethod
    @property
    def best_match_implemented(cls):
        return True

    async def _search(self, url: str):
        from PicImageSearch import Network
        async with Network() as client:
            engine = self.pic_engine_class(client=client)
            return await engine.search(url=url)

    def _extract(self, raw: list) -> InternalProviderData:
        """Default extractor — works for most engines with title/url/thumbnail attrs."""
        r = raw[0]
        result = {}
        meta: MetaData = {}

        if title := getattr(r, "title", None):
            result["Title"] = title

        buttons = []
        if link := getattr(r, "url", None):
            buttons.append(url_button(link))
        if buttons:
            meta["buttons"] = buttons

        if thumb := getattr(r, "thumbnail", None):
            meta["thumbnail"] = URL(thumb)

        return result, meta

    @cached(GenericRISEngine._best_match_cache)
    def best_match(self, url: str | URL) -> ProviderData:
        self.logger.debug("Started looking for %s", url)
        meta: MetaData = {
            "provider": self.name,
            "provider_url": self.provider_url,
        }

        try:
            result_obj = asyncio.run(self._search(str(url)))
        except Exception as e:
            self.logger.warning("Search failed: %s", e)
            return {}, {**meta, "errors": [str(e)]}

        if not getattr(result_obj, "raw", None):
            self.logger.debug("Done: no results")
            return {}, meta

        try:
            r, m = self._extract(result_obj.raw)
        except Exception as e:
            self.logger.warning("Extraction failed: %s", e)
            return {}, meta

        meta.update(m)
        self.logger.debug("Done: found something")
        return self._clean_best_match(r, meta)
