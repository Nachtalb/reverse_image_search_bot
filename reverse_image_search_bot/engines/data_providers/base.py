from functools import partial, wraps
import logging
from typing import TypedDict

from cachetools import TTLCache, cachedmethod
from cachetools.keys import hashkey
from requests import Session


def provider_cache(func):
    return wraps(func)(cachedmethod(lambda self: self._cache, key=partial(hashkey, func.__qualname__))(func))


class ProviderInfo(TypedDict):
    name: str  # Example Website
    url: str  # https://example.tld
    site_type: str  # Imageboard or Anime DB etc.
    types: list[str]  # Anime, Manga


class BaseProvider:
    info: ProviderInfo = {"name": "Base", "url": "", "types": [], "site_type": ""}
    infos: dict[str, ProviderInfo] = {}
    _cache_ttl = 30 * 24 * 60 * 60

    def __init__(self):
        self._cache: TTLCache = TTLCache(1e4, self._cache_ttl)
        self.session: Session = Session()
        self.logger: logging.Logger = logging.getLogger(self.info["name"] + "DataProvider")
