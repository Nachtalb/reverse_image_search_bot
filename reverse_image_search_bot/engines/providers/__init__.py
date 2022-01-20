from .anilist import AnilistProvider
from .boorus import BooruProviders
from .mangadex import MangadexProvider


class ProviderCollection(AnilistProvider, BooruProviders, MangadexProvider):
    pass
