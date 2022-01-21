from .anilist import AnilistProvider
from .base import BaseProvider
from .boorus import BooruProvider
from .mangadex import MangadexProvider

__all__ = ["anilist", "booru", "mangadex", "provides"]

anilist = AnilistProvider()
booru = BooruProvider()
mangadex = MangadexProvider()

provides: list[BaseProvider] = [anilist, booru, mangadex]
