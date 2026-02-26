from __future__ import annotations

import asyncio
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
    """Strip parenthetical readings, nicknames after comma, etc."""
    # "矢澤 にこ（やざわ にこ）"  → "矢澤 にこ"
    # "ヤシロ・モモカ, Momo"      → "ヤシロ・モモカ"
    # "シリカ (Scilica)  綾野珪子" → "シリカ"
    return name.split("（")[0].split("(")[0].split(",")[0].strip()


@lru_cache(maxsize=256)
def _anilist_english_name(japanese_name: str) -> str:
    """Look up English character name via AniList. Returns original if not found."""
    clean = _clean_name(japanese_name)
    try:
        import httpx
        r = httpx.post(
            "https://graphql.anilist.co",
            json={"query": _ANILIST_CHAR_QUERY, "variables": {"name": clean}},
            timeout=5,
        )
        r.raise_for_status()
        full = r.json()["data"]["Character"]["name"]["full"]
        return full or japanese_name
    except Exception:
        return japanese_name


@lru_cache(maxsize=256)
def _anilist_english_work(work: str) -> str:
    """Look up English series title via AniList. Returns original if not found."""
    try:
        import httpx
        r = httpx.post(
            "https://graphql.anilist.co",
            json={"query": _ANILIST_MEDIA_QUERY, "variables": {"title": work}},
            timeout=5,
        )
        r.raise_for_status()
        titles = r.json()["data"]["Media"]["title"]
        return titles.get("english") or titles.get("romaji") or work
    except Exception:
        return work


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
            "Work": _anilist_english_work(top.work),
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
