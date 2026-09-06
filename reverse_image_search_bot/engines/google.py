"""Google engine — Lens link button plus a Vision API WEB_DETECTION best match.

Google killed the old ``/searchbyimage`` endpoint and Lens cannot be scraped
(JS interstitial, ``/sorry`` captcha from datacenter IPs), so the inline result
comes from the Cloud Vision API instead. Its free tier is 1000 units/month, so
usage is counted client-side in a small JSON file next to the config DB; when
the month's budget is spent we raise :class:`RateLimitError` and the user still
gets the Lens button.

The engine stays completely dormant when ``GOOGLE_VISION_API`` is unset — no
requests, no quota file, and ``best_match_implemented`` is False so the search
flow never even schedules it.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx
from yarl import URL

from reverse_image_search_bot import settings
from reverse_image_search_bot.utils.async_cache import async_cached
from reverse_image_search_bot.utils.url import url_button

from .errors import RateLimitError, SearchError, is_transient
from .generic import GenericRISEngine, _classproperty
from .types import InternalResultData, MetaData, ProviderData

__all__ = ["GoogleEngine"]

_VISION_URL = "https://vision.googleapis.com/v1/images:annotate"

#: How many web-detection results to ask Vision for.
_MAX_RESULTS = 10
#: How many "page containing the image" buttons to offer.
_MAX_PAGE_BUTTONS = 3
#: How many web entity labels to list in the result body.
_MAX_ENTITIES = 5
#: Vision scores entities 0..1; below this they are mostly noise.
_MIN_ENTITY_SCORE = 0.3


class GoogleEngine(GenericRISEngine):
    name = "Google"
    description = (
        "Google LLC is an American multinational technology company that specializes in Internet-related services and"
        " products."
    )
    provider_url = URL("https://google.com/")
    types = ["General"]
    recommendation = ["Anything SFW", "People and Characters"]

    url = "https://lens.google.com/uploadbyurl?url={query_url}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._http_client = httpx.AsyncClient(timeout=10)
        self._quota_lock = asyncio.Lock()

    @_classproperty
    def best_match_implemented(cls):
        # Read at call time, not import time, so tests (and a later reconfigure)
        # can flip the key without rebuilding the engine list.
        return bool(settings.GOOGLE_VISION_API)

    # --- quota ------------------------------------------------------------

    def _read_quota(self) -> tuple[str, int]:
        """Return (month, count) from the quota file, resetting on a new month."""
        month = datetime.now(UTC).strftime("%Y-%m")
        try:
            data = json.loads(settings.GOOGLE_VISION_QUOTA_PATH.read_text())
        except OSError, ValueError:
            # Missing (first run) or corrupted file — start the month over
            # rather than blocking every search on it.
            return month, 0
        if not isinstance(data, dict) or data.get("month") != month:
            return month, 0
        try:
            return month, int(data.get("count", 0))
        except ValueError, TypeError:
            return month, 0

    def _take_quota(self) -> bool:
        """Consume one unit of the monthly Vision budget. False when spent."""
        month, count = self._read_quota()
        if count >= settings.GOOGLE_VISION_MONTHLY_LIMIT:
            return False
        path = settings.GOOGLE_VISION_QUOTA_PATH
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"month": month, "count": count + 1}))
        except OSError as e:
            # An unwritable quota file must not silently uncap spending.
            self.logger.info("Google Vision quota file not writable (%s) — skipping lookup", e)
            return False
        return True

    # --- response parsing -------------------------------------------------

    def _extract(self, web: dict[str, Any]) -> tuple[InternalResultData, MetaData]:
        full = [i for i in web.get("fullMatchingImages", []) if i.get("url")]
        partial = [i for i in web.get("partialMatchingImages", []) if i.get("url")]
        pages = [p for p in web.get("pagesWithMatchingImages", []) if p.get("url")]

        if not full and not partial and not pages:
            return {}, {}

        result: InternalResultData = {}
        meta: MetaData = {"provider": self.name, "provider_url": self.provider_url}

        labels = web.get("bestGuessLabels") or []
        if labels and (label := labels[0].get("label")):
            result["Best guess"] = str(label).title()

        if pages and (page_title := pages[0].get("pageTitle")):
            result["Title"] = _strip_tags(str(page_title))

        entities = [
            str(e["description"])
            for e in web.get("webEntities", [])
            if e.get("description") and float(e.get("score", 0)) >= _MIN_ENTITY_SCORE
        ]
        if entities:
            result["Tags"] = entities[:_MAX_ENTITIES]

        result["Match"] = "Full" if full else ("Partial" if partial else "Pages only")
        if pages:
            result["Found on"] = f"{len(pages)} page(s)"

        buttons = [url_button(p["url"], fix_url_=False) for p in pages[:_MAX_PAGE_BUTTONS]]
        if buttons:
            meta["buttons"] = buttons

        # Prefer a full match for the preview image; a partial one still shows
        # the right subject most of the time.
        if thumb := next((i["url"] for i in [*full, *partial]), None):
            meta["thumbnail"] = URL(thumb)
            meta["thumbnail_identifier"] = thumb

        # Dedupe key against other engines: the page we point the user at.
        if pages:
            meta["identifier"] = str(pages[0]["url"])

        return result, meta

    # --- lookup -----------------------------------------------------------

    @async_cached(GenericRISEngine._best_match_cache)
    async def best_match(self, url: str | URL) -> ProviderData:
        self.logger.debug("Started looking for %s", url)
        if not settings.GOOGLE_VISION_API:
            # No key configured — the Lens button is all we can offer.
            return {}, {}

        async with self._quota_lock:
            has_quota = self._take_quota()
        if not has_quota:
            raise RateLimitError("Google Vision monthly quota exhausted", period="Monthly")

        body = {
            "requests": [
                {
                    "image": {"source": {"imageUri": str(url)}},
                    "features": [{"type": "WEB_DETECTION", "maxResults": _MAX_RESULTS}],
                }
            ]
        }
        try:
            response = await self._http_client.post(_VISION_URL, params={"key": settings.GOOGLE_VISION_API}, json=body)
        except Exception as e:
            detail = str(e) or type(e).__name__
            raise SearchError(f"Google Vision request failed: {detail}", report=not is_transient(e)) from e

        if response.status_code == 429:
            raise RateLimitError("Google Vision 429", period="Monthly")
        if response.status_code >= 500:
            # Google-side hiccup, not our bug.
            raise SearchError(f"Google Vision HTTP {response.status_code}", report=False)
        if response.status_code != 200:
            # 4xx means our key or request is wrong — worth reporting.
            raise SearchError(f"Google Vision HTTP {response.status_code}")

        try:
            payload = response.json()
            first = payload["responses"][0]
        except Exception as e:
            raise SearchError(f"Bad Google Vision response body: {e}", report=False) from e

        if error := first.get("error"):
            # e.g. the uploader URL was unreachable from Google's side.
            raise SearchError(f"Google Vision error: {error.get('message', error)}", report=False)

        result, meta = self._extract(first.get("webDetection") or {})
        if not result:
            self.logger.debug("Done: no results")
            return {}, {}

        self.logger.debug("Done: found something")
        return self._clean_best_match(result, meta)


def _strip_tags(text: str) -> str:
    """Page titles occasionally arrive with <b> highlight markup."""
    out = []
    depth = 0
    for char in text:
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(depth - 1, 0)
        elif depth == 0:
            out.append(char)
    return " ".join("".join(out).split())
