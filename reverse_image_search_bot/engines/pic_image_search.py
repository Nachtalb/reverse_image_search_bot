"""
Generic base engine for PicImageSearch-backed engines.
Each subclass sets `pic_engine_class` and optionally overrides `_extract`.
"""

from yarl import URL

from reverse_image_search_bot.utils.async_cache import async_cached
from reverse_image_search_bot.utils.url import url_button

from .errors import SearchError
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
            assert self.pic_engine_class, "pic_engine_class must be set on subclass"
            engine = self.pic_engine_class(client=client)
            return await engine.search(url=url)

    async def _extract(self, raw: list) -> InternalProviderData:
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

    @async_cached(GenericRISEngine._best_match_cache)
    async def best_match(self, url: str | URL) -> ProviderData:
        self.logger.debug("Started looking for %s", url)
        meta: MetaData = {
            "provider": self.name,
            "provider_url": self.provider_url,
        }

        try:
            result_obj = await self._search(str(url))
        except KeyError as e:
            raise SearchError(f"Parsing key missing: {e}") from e
        except Exception as e:
            from PicImageSearch.exceptions import ParsingError

            if isinstance(e, ParsingError):
                raise SearchError(f"ParsingError: {e}") from e
            raise SearchError(f"Search failed: {e}") from e

        if not getattr(result_obj, "raw", None):
            self.logger.debug("Done: no results")
            return {}, {}

        try:
            r, m = await self._extract(result_obj.raw)
        except Exception as e:
            raise SearchError(f"Extraction failed: {e}") from e

        if not r:
            self.logger.debug("Done: extraction yielded nothing")
            return {}, {}

        meta.update(m)
        self.logger.debug("Done: found something")
        return self._clean_best_match(r, meta)
