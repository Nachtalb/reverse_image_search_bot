from .anilist import AnilistProvider
from .base import BaseProvider
from .boorus import BooruProvider
from .mangadex import MangadexProvider
from .pixiv import PixivProvider

__all__ = ["anilist", "booru", "mangadex", "provides", "pixiv"]

anilist = AnilistProvider()
booru = BooruProvider()
mangadex = MangadexProvider()
pixiv = PixivProvider()

provides: list[BaseProvider] = [anilist, booru, mangadex, pixiv]
