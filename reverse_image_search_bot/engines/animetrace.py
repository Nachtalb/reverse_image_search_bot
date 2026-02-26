from __future__ import annotations

import asyncio
from functools import lru_cache

from yarl import URL

from .pic_image_search import PicImageSearchEngine
from .types import InternalProviderData, MetaData

__all__ = ["AnimeTraceEngine"]

_ANILIST_QUERY = """
query ($name: String) {
  Character(search: $name) {
    name { full }
  }
}
"""


@lru_cache(maxsize=256)
def _anilist_english_name(japanese_name: str) -> str:
    """Look up English name via AniList. Returns original if not found."""
    # Strip parenthetical readings, e.g. "矢澤 にこ（やざわ にこ）" → "矢澤 にこ"
    clean = japanese_name.split("（")[0].split("(")[0].strip()
    try:
        import httpx
        r = httpx.post(
            "https://graphql.anilist.co",
            json={"query": _ANILIST_QUERY, "variables": {"name": clean}},
            timeout=5,
        )
        r.raise_for_status()
        full = r.json()["data"]["Character"]["name"]["full"]
        return full or japanese_name
    except Exception:
        return japanese_name


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

    def _extract(self, raw: list) -> InternalProviderData:
        item = raw[0]
        characters = getattr(item, "characters", [])
        if not characters:
            return {}, {}

        top = characters[0]
        en_name = _anilist_english_name(top.name)

        result = {
            "Character": en_name,
            "Work": top.work,
        }

        others = [
            _anilist_english_name(c.name)
            for c in characters[1:4]
            if c.name != top.name
        ]
        # Deduplicate while preserving order
        seen: set[str] = {en_name}
        unique_others = []
        for n in others:
            if n not in seen:
                seen.add(n)
                unique_others.append(n)

        if unique_others:
            result["Also possible"] = ", ".join(unique_others)

        meta: MetaData = {}
        if thumb := getattr(item, "thumbnail", None):
            meta["thumbnail"] = URL(thumb)

        return result, meta
