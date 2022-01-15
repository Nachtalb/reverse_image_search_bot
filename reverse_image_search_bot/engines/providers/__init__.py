from .anilist import AnilistProvider
from .boorus import BooruProviders


class ProviderCollection(AnilistProvider, BooruProviders):
    pass
