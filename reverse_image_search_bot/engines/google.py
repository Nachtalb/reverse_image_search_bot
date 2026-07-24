"""Google engine — Lens URL button + Vision API WEB_DETECTION best match.

The best match uses the Google Cloud Vision API (1000 free units/month).
Usage is tracked in a small JSON file next to the config DB so the counter
survives restarts; when the monthly budget is spent the engine raises
RateLimitError until the next calendar month (UTC).
"""

import json
from datetime import UTC, datetime

import httpx
from yarl import URL

from reverse_image_search_bot import settings
from reverse_image_search_bot.utils import url_button
from reverse_image_search_bot.utils.async_cache import async_cached

from .errors import RateLimitError, SearchError, is_transient
from .generic import GenericRISEngine, _classproperty
from .types import InternalResultData, MetaData, ProviderData

__all__ = ["GoogleEngine"]

_VISION_URL = "https://vision.googleapis.com/v1/images:annotate"


class GoogleEngine(GenericRISEngine):
    name = "Google"
    description = (
        "Google LLC is an American multinational technology company that specializes in Internet-related"
        " services and products."
    )
    provider_url = URL("https://google.com/")
    types = ["General"]
    recommendation = ["Anything SFW", "People and Characters"]
    url = "https://lens.google.com/uploadbyurl?url={query_url}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._http_client = httpx.AsyncClient(timeout=10)

    @_classproperty
    def best_match_implemented(cls):
        return bool(settings.GOOGLE_VISION_API)

    def _take_quota(self) -> bool:
        """Consume one unit of the monthly Vision budget. False when spent."""
        path = settings.GOOGLE_VISION_QUOTA_PATH
        month = datetime.now(UTC).strftime("%Y-%m")
        count = 0
        try:
            data = json.loads(path.read_text())
            if data.get("month") == month:
                count = int(data.get("count", 0))
        except OSError, ValueError:
            pass
        if count >= settings.GOOGLE_VISION_MONTHLY_LIMIT:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"month": month, "count": count + 1}))
        return True

    @async_cached(GenericRISEngine._best_match_cache)
    async def best_match(self, url: str | URL) -> ProviderData:
        self.logger.debug("Started looking for %s", url)
        if not settings.GOOGLE_VISION_API:
            return {}, {}
        if not self._take_quota():
            raise RateLimitError("Google Vision monthly quota exhausted", period="Monthly")

        body = {
            "requests": [
                {
                    "image": {"source": {"imageUri": str(url)}},
                    "features": [{"type": "WEB_DETECTION", "maxResults": 10}],
                }
            ]
        }
        try:
            response = await self._http_client.post(_VISION_URL, params={"key": settings.GOOGLE_VISION_API}, json=body)
        except Exception as e:
            detail = str(e) or type(e).__name__
            raise SearchError(f"Search failed: {detail}", report=not is_transient(e)) from e

        if response.status_code == 429:
            raise RateLimitError("Google Vision 429", period="Monthly")
        if response.status_code != 200:
            # 5xx = Google hiccup, not our bug; 4xx = our request/key is wrong.
            raise SearchError(f"Google Vision HTTP {response.status_code}", report=response.status_code < 500)

        try:
            web = response.json()["responses"][0].get("webDetection", {})
        except (json.JSONDecodeError, LookupError) as e:
            raise SearchError(f"Bad response body: {e}", report=False) from e

        full = web.get("fullMatchingImages", [])
        partial = web.get("partialMatchingImages", [])
        pages = web.get("pagesWithMatchingImages", [])
        if not full and not partial and not pages:
            self.logger.debug("Done: no results")
            return {}, {}

        result: InternalResultData = {}
        meta: MetaData = {"provider": self.name, "provider_url": self.provider_url}

        if labels := web.get("bestGuessLabels"):
            result["Best guess"] = labels[0].get("label")
        if pages and (title := pages[0].get("pageTitle")):
            result["Title"] = title
        result["Match"] = "Full" if full else ("Partial" if partial else None)

        buttons = []
        for page in pages[:3]:
            if link := page.get("url"):
                buttons.append(url_button(link, fix_url_=False))
        if buttons:
            meta["buttons"] = buttons

        if thumb := next((i.get("url") for i in [*full, *partial] if i.get("url")), None):
            meta["thumbnail"] = URL(thumb)
            meta["thumbnail_identifier"] = thumb

        self.logger.debug("Done: found something")
        return self._clean_best_match(result, meta)
