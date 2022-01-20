from itertools import repeat

from .anilist import AnilistProvider
from .boorus import BooruProviders
from .mangadex import MangadexProvider


class ProviderCollection(AnilistProvider, BooruProviders, MangadexProvider):
    __provider_info = []

    @staticmethod
    def data_provider_info() -> list[dict]:
        cls = ProviderCollection
        if not cls.__provider_info:
            for base in cls.__bases__:
                if base is object:
                    continue

                if isinstance(base.provider_name, list):
                    data = zip(base.provider_name, base.provider_url, repeat(base.provides))
                else:
                    data = [(base.provider_name, base.provider_url, base.provides)]

                for name, url, provides in data:
                    cls.__provider_info.append({"name": name, "url": url, "provides": provides})
        return cls.__provider_info
