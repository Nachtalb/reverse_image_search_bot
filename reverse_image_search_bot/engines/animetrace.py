from __future__ import annotations

from functools import lru_cache

from yarl import URL

from .pic_image_search import PicImageSearchEngine
from .types import InternalProviderData, MetaData

__all__ = ["AnimeTraceEngine"]

_ANILIST_CHAR_QUERY = """
query ($name: String) {
  Character(search: $name) {
    name { full }
  }
}
"""

_ANILIST_MEDIA_QUERY = """
query ($title: String) {
  Media(search: $title) {
    title { english romaji }
  }
}
"""


def _clean_name(name: str) -> str:
    """Strip parenthetical readings, nicknames after comma, etc.

    "矢澤 にこ（やざわ にこ）"  → "矢澤 にこ"
    "ヤシロ・モモカ, Momo"      → "ヤシロ・モモカ"
    "シリカ (Scilica)  綾野珪子" → "シリカ"
    """
    return name.split("（")[0].split("(")[0].split(",")[0].strip()


def _anilist_post(payload: dict) -> dict | None:
    """POST to AniList GraphQL with one retry on 429."""
    import time
    import httpx
    for attempt in range(2):
        r = httpx.post("https://graphql.anilist.co", json=payload, timeout=5)
        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", "1"))
            time.sleep(retry_after + 0.1)
            continue
        r.raise_for_status()
        return r.json()
    return None


@lru_cache(maxsize=256)
def _anilist_english_name(japanese_name: str) -> str:
    """Look up English character name via AniList. Returns original if not found."""
    clean = _clean_name(japanese_name)
    try:
        data = _anilist_post({"query": _ANILIST_CHAR_QUERY, "variables": {"name": clean}})
        full = data["data"]["Character"]["name"]["full"]
        return full or japanese_name
    except Exception:
        return japanese_name


@lru_cache(maxsize=256)
def _anilist_english_work(work: str) -> str:
    """Look up English series title via AniList. Returns original if not found."""
    try:
        data = _anilist_post({"query": _ANILIST_MEDIA_QUERY, "variables": {"title": work}})
        titles = data["data"]["Media"]["title"]
        return titles.get("english") or titles.get("romaji") or work
    except Exception:
        return work


def _resolve_character(name: str, work: str) -> tuple[str, str]:
    """Resolve a character name and series to English. Returns (en_name, en_work)."""
    return _anilist_english_name(name), _anilist_english_work(work)


class AnimeTraceEngine(PicImageSearchEngine):
    name = "AnimeTrace"
    description = (
        "AnimeTrace identifies anime characters in images, returning the "
        "character name and source work."
    )
    provider_url = URL("https://animetrace.moe/")
    types = ["Anime/Manga"]
    recommendation = ["Anime characters", "Fan art"]
    url = "https://animetrace.moe/"

    def __init__(self, *args, **kwargs):
        from PicImageSearch import AnimeTrace
        self.pic_engine_class = AnimeTrace
        super().__init__(*args, **kwargs)

    async def _search(self, url: str):
        from PicImageSearch import AnimeTrace, Network
        async with Network() as client:
            # is_multi=1: detect all characters in the image, not just the dominant one
            engine = AnimeTrace(client=client, is_multi=1)
            return await engine.search(url=url)

    def _extract(self, raw: list) -> InternalProviderData:
        # Filter out low-confidence detections
        confident = [item for item in raw if not item.origin.get("not_confident", False)]
        if not confident:
            # Fall back to all results with a warning if everything is low confidence
            confident = raw

        result: dict = {}
        meta: MetaData = {}

        if len(confident) == 1:
            # Single character detected — full detail format
            item = confident[0]
            characters = getattr(item, "characters", [])
            if not characters:
                return {}, {}

            top = characters[0]
            en_name, en_work = _resolve_character(top.name, top.work)

            result["Character"] = en_name
            result["Work"] = en_work

            if item.origin.get("not_confident"):
                result["Note"] = "Low confidence match"

            # Alternate candidates (name + work for disambiguation)
            seen_names: set[str] = {en_name}
            alts = []
            for c in characters[1:4]:
                if c.name == top.name:
                    continue
                alt_name, alt_work = _resolve_character(c.name, c.work)
                if alt_name not in seen_names:
                    seen_names.add(alt_name)
                    alts.append(f"{alt_name} ({alt_work})")
            if alts:
                result["Also possible"] = ", ".join(alts)

        else:
            # Multiple characters detected — compact list format
            entries = []
            for item in confident:
                characters = getattr(item, "characters", [])
                if not characters:
                    continue
                top = characters[0]
                en_name, en_work = _resolve_character(top.name, top.work)
                confidence = " (?)" if item.origin.get("not_confident") else ""
                entries.append(f"{en_name}{confidence} ({en_work})")

            if not entries:
                return {}, {}
            result["Characters"] = ", ".join(entries)

        if thumb := getattr(confident[0], "thumbnail", None):
            meta["thumbnail"] = URL(thumb)

        return result, meta
