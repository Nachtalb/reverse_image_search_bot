from __future__ import annotations

import re
import time
from functools import lru_cache

import httpx
from telegram import InlineKeyboardButton
from yarl import URL

from .data_providers import anilist as anilist_provider
from .pic_image_search import PicImageSearchEngine
from .types import InternalProviderData, MetaData

__all__ = ["AnimeTraceEngine"]

_ANILIST_QUERY = """
query ($name: String) {
  Character(search: $name) {
    id
    name { full }
    siteUrl
    media(perPage: 10, sort: POPULARITY_DESC) {
      nodes { id type siteUrl title { english romaji native } }
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
    return re.split(r"[（(,]", name)[0].strip()


def _anilist_post(payload: dict) -> dict | None:
    """POST to AniList GraphQL with one retry on 429."""
    for _ in range(2):
        r = httpx.post("https://graphql.anilist.co", json=payload, timeout=5)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "1")) + 0.1)
            continue
        r.raise_for_status()
        return r.json()
    return None


def _best_work_node(media_nodes: list, original_work: str) -> tuple[str, int | None]:
    """Find the best matching work node and return (english_title, anilist_id).

    Returns (original_work, None) if no match found.
    """
    if not media_nodes:
        return original_work, None

    orig_lower = original_work.lower()
    for node in media_nodes:
        t = node["title"]
        native = (t.get("native") or "").lower()
        romaji = (t.get("romaji") or "").lower()
        if orig_lower in (native, romaji) or native in orig_lower or romaji in orig_lower:
            title = t.get("english") or t.get("romaji") or original_work
            return title, node.get("id")

    # Fallback to most popular node
    node = media_nodes[0]
    t = node["title"]
    title = t.get("english") or t.get("romaji") or original_work
    return title, node.get("id")


@lru_cache(maxsize=256)
def _anilist_resolve(char_name: str, work: str) -> tuple[str, str, int | None, int | None]:
    """Resolve character name and work to English via AniList.

    Returns (english_char_name, english_work_title, anilist_char_id, anilist_media_id).
    Falls back to originals on failure; IDs are None on failure.
    """
    clean = _clean_name(char_name)
    try:
        data = _anilist_post({"query": _ANILIST_QUERY, "variables": {"name": clean}})
        char = data["data"]["Character"]
        en_name = char["name"]["full"] or char_name
        char_id = char.get("id")
        en_work, media_id = _best_work_node(char["media"]["nodes"], work)
        return en_name, en_work, char_id, media_id
    except Exception:
        return char_name, work, None, None


class AnimeTraceEngine(PicImageSearchEngine):
    name = "AnimeTrace"
    description = (
        "AnimeTrace identifies anime characters in images, returning the "
        "character name and source work."
    )
    provider_url = URL("https://www.animetrace.com/")
    types = ["Anime/Manga"]
    recommendation = ["Anime characters", "Fan art"]
    url = "https://www.animetrace.com/"

    def __init__(self, *args, **kwargs):
        from PicImageSearch import AnimeTrace
        self.pic_engine_class = AnimeTrace
        super().__init__(*args, **kwargs)

    async def _search(self, url: str):
        from PicImageSearch import AnimeTrace, Network
        async with Network() as client:
            engine = AnimeTrace(client=client, is_multi=1)
            return await engine.search(url=url)

    def _extract(self, raw: list) -> InternalProviderData:
        confident = [item for item in raw if not item.origin.get("not_confident", False)]
        if not confident:
            return {}, {}

        result: dict = {}
        meta: MetaData = {}

        if len(confident) == 1:
            item = confident[0]
            characters = getattr(item, "characters", [])
            if not characters:
                return {}, {}

            top = characters[0]
            en_name, en_work, char_id, media_id = _anilist_resolve(top.name, top.work)

            result["Character"] = en_name
            result["Work"] = en_work

            # Enrich with AniList media data (status, year, genres, etc.)
            al_meta: MetaData = {}
            if media_id:
                al_result, al_meta = anilist_provider.provide(media_id)
                if al_result:
                    # Skip Title/Title[romaji] (we have Work) and Episode (unknown)
                    for key in ("Title", "Title [romaji]", "Episode"):
                        al_result.pop(key, None)
                    result.update(al_result)
                if al_meta:
                    meta["provided_via"] = al_meta.get("provided_via")
                    meta["provided_via_url"] = al_meta.get("provided_via_url")
                    # Use AniList cover as thumbnail fallback
                    if not getattr(confident[0], "thumbnail", None):
                        meta["thumbnail"] = al_meta.get("thumbnail")

            # Build buttons: character page + media page
            buttons: list[InlineKeyboardButton] = []
            if char_id:
                buttons.append(
                    InlineKeyboardButton(
                        text=f"👤 {en_name}",
                        url=f"https://anilist.co/character/{char_id}",
                    )
                )
            if media_id and al_meta and al_meta.get("buttons"):
                buttons.extend(al_meta["buttons"])
            if buttons:
                meta["buttons"] = buttons

            seen_names: set[str] = {en_name}
            alts = []
            for c in characters[1:4]:
                if c.name == top.name:
                    continue
                alt_name, alt_work, _, _ = _anilist_resolve(c.name, c.work)
                if alt_name not in seen_names:
                    seen_names.add(alt_name)
                    alts.append(f"{alt_name} ({alt_work})")
            if alts:
                result["Also possible"] = ", ".join(alts)

        else:
            entries = []
            for item in confident:
                characters = getattr(item, "characters", [])
                if not characters:
                    continue
                top = characters[0]
                en_name, en_work, _, _ = _anilist_resolve(top.name, top.work)
                entries.append(f"{en_name} ({en_work})")

            if not entries:
                return {}, {}
            result["Characters"] = ", ".join(entries)

        if thumb := getattr(confident[0], "thumbnail", None):
            meta["thumbnail"] = URL(thumb)

        return result, meta
