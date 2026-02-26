from __future__ import annotations

from functools import lru_cache

from yarl import URL

from .pic_image_search import PicImageSearchEngine
from .types import InternalProviderData, MetaData

__all__ = ["AnimeTraceEngine"]

# Single query: character English name + their media list (for work title)
_ANILIST_QUERY = """
query ($name: String) {
  Character(search: $name) {
    name { full }
    media(perPage: 10, sort: POPULARITY_DESC) {
      nodes { title { english romaji native } }
    }
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


def _best_work_title(media_nodes: list, original_work: str) -> str:
    """Find the best English work title from a character's media list.

    First tries to match the original work string against native/romaji titles.
    Falls back to the most popular media's English/romaji title.
    """
    if not media_nodes:
        return original_work

    # Try to match AnimeTrace's work against native or romaji titles
    orig_lower = original_work.lower()
    for node in media_nodes:
        t = node["title"]
        native = (t.get("native") or "").lower()
        romaji = (t.get("romaji") or "").lower()
        if orig_lower in (native, romaji) or native in orig_lower or romaji in orig_lower:
            return t.get("english") or t.get("romaji") or original_work

    # No match — use the most popular entry (first after POPULARITY_DESC sort)
    t = media_nodes[0]["title"]
    return t.get("english") or t.get("romaji") or original_work


@lru_cache(maxsize=256)
def _anilist_resolve(char_name: str, work: str) -> tuple[str, str]:
    """Resolve character name and work to English in a single AniList call.

    Returns (english_char_name, english_work_title).
    Falls back to originals on failure.
    """
    clean = _clean_name(char_name)
    try:
        data = _anilist_post({"query": _ANILIST_QUERY, "variables": {"name": clean}})
        char = data["data"]["Character"]
        en_name = char["name"]["full"] or char_name
        en_work = _best_work_title(char["media"]["nodes"], work)
        return en_name, en_work
    except Exception:
        return char_name, work


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
            confident = raw  # fall back to all if everything is uncertain

        result: dict = {}
        meta: MetaData = {}

        if len(confident) == 1:
            # Single character — full detail format
            item = confident[0]
            characters = getattr(item, "characters", [])
            if not characters:
                return {}, {}

            top = characters[0]
            en_name, en_work = _anilist_resolve(top.name, top.work)

            result["Character"] = en_name
            result["Work"] = en_work

            if item.origin.get("not_confident"):
                result["Note"] = "Low confidence match"

            # Alternate candidates with works for disambiguation
            seen_names: set[str] = {en_name}
            alts = []
            for c in characters[1:4]:
                if c.name == top.name:
                    continue
                alt_name, alt_work = _anilist_resolve(c.name, c.work)
                if alt_name not in seen_names:
                    seen_names.add(alt_name)
                    alts.append(f"{alt_name} ({alt_work})")
            if alts:
                result["Also possible"] = ", ".join(alts)

        else:
            # Multiple characters — compact list
            entries = []
            for item in confident:
                characters = getattr(item, "characters", [])
                if not characters:
                    continue
                top = characters[0]
                en_name, en_work = _anilist_resolve(top.name, top.work)
                confidence = " (?)" if item.origin.get("not_confident") else ""
                entries.append(f"{en_name}{confidence} ({en_work})")

            if not entries:
                return {}, {}
            result["Characters"] = ", ".join(entries)

        if thumb := getattr(confident[0], "thumbnail", None):
            meta["thumbnail"] = URL(thumb)

        return result, meta
