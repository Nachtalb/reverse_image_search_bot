from yarl import URL

from .pic_image_search import PicImageSearchEngine
from .types import InternalProviderData, MetaData

__all__ = ["AnimeTraceEngine"]


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
        result = {
            "Character": top.name,
            "Work": top.work,
        }

        others = [
            f"{c.name} ({c.work})"
            for c in characters[1:4]
            if c.name != top.name
        ]
        if others:
            result["Also possible"] = ", ".join(others)

        meta: MetaData = {}
        if thumb := getattr(item, "thumbnail", None):
            meta["thumbnail"] = URL(thumb)

        return result, meta
