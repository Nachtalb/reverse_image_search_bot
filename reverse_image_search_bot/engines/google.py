"""Google Reverse Image Search engine via SerpAPI."""

import asyncio

from yarl import URL

from reverse_image_search_bot.settings import SERPAPI_KEY
from reverse_image_search_bot.utils.async_cache import async_cached
from reverse_image_search_bot.utils.url import url_button

from .errors import SearchError
from .generic import GenericRISEngine
from .types import InternalProviderData, MetaData, ProviderData

__all__ = ["GoogleEngine"]


class GoogleEngine(GenericRISEngine):
    name = "Google"
    description = "Google Reverse Image Search — finds pages containing the image and visually similar images."
    provider_url = URL("https://www.google.com/")
    types = ["General"]
    recommendation = ["Anything SFW", "People and Characters", "General"]
    premium_only = True

    url = "https://www.google.com/searchbyimage?safe=off&sbisrc=tg&image_url={query_url}"

    @classmethod
    @property
    def best_match_implemented(cls):
        return bool(SERPAPI_KEY)

    @async_cached(GenericRISEngine._best_match_cache)
    async def best_match(self, url: str | URL) -> ProviderData:
        self.logger.debug("Started looking for %s", url)
        meta: MetaData = {
            "provider": self.name,
            "provider_url": self.provider_url,
        }

        if not SERPAPI_KEY:
            raise SearchError("SERPAPI_KEY not configured")

        try:
            result_data = await asyncio.to_thread(self._search_sync, str(url))
        except Exception as e:
            raise SearchError(f"SerpAPI search failed: {e}") from e

        if not result_data:
            self.logger.debug("Done: no results")
            return {}, {}

        result, m = self._extract(result_data)
        if not result:
            self.logger.debug("Done: extraction yielded nothing")
            return {}, {}

        meta.update(m)
        self.logger.debug("Done: found something")
        return self._clean_best_match(result, meta)

    @staticmethod
    def _search_sync(image_url: str) -> list[dict]:
        """Run the SerpAPI search synchronously (called via to_thread)."""
        import serpapi

        client = serpapi.Client(api_key=SERPAPI_KEY)
        results = client.search(
            {
                "engine": "google_reverse_image",
                "image_url": image_url,
                "hl": "en",
                "gl": "us",
            }
        )
        return results.get("image_results", [])

    @staticmethod
    def _extract(raw: list[dict]) -> InternalProviderData:
        """Extract the best result from SerpAPI response."""
        if not raw:
            return {}, {}

        r = raw[0]
        result = {}
        meta: MetaData = {}

        if title := r.get("title"):
            result["Title"] = title

        if source := r.get("source"):
            result["Source"] = source

        buttons = []
        if link := r.get("link"):
            buttons.append(url_button(link))
        if buttons:
            meta["buttons"] = buttons

        if thumbnail := r.get("thumbnail"):
            meta["thumbnail"] = URL(thumbnail)

        # Use link as identifier for dedup
        if link := r.get("link"):
            meta["identifier"] = link

        return result, meta
