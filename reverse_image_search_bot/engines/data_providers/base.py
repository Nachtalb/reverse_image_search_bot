from functools import partial, wraps
import logging
import time
from typing import TypedDict

from cachetools import TTLCache, cachedmethod
from cachetools.keys import hashkey
from requests import Session

from reverse_image_search_bot import metrics


def provider_cache(func):
    return wraps(func)(cachedmethod(lambda self: self._cache, key=partial(hashkey, func.__qualname__))(func))


def _instrumented_provide(original_provide):
    """Wrap a data provider's provide() method with metrics tracking."""
    @wraps(original_provide)
    def wrapper(self, *args, **kwargs):
        provider_name = self.info.get("name", type(self).__name__).lower()
        start = time.time()
        try:
            result, meta = original_provide(self, *args, **kwargs)
            duration = time.time() - start
            metrics.data_provider_duration_seconds.labels(provider=provider_name).observe(duration)
            if result:
                metrics.data_provider_total.labels(provider=provider_name, status="hit").inc()
            else:
                metrics.data_provider_total.labels(provider=provider_name, status="miss").inc()
            return result, meta
        except Exception:
            duration = time.time() - start
            metrics.data_provider_duration_seconds.labels(provider=provider_name).observe(duration)
            metrics.data_provider_total.labels(provider=provider_name, status="error").inc()
            raise
    return wrapper


class ProviderInfo(TypedDict):
    name: str  # Example Website
    url: str  # https://example.tld
    site_type: str  # Imageboard or Anime DB etc.
    types: list[str]  # Anime, Manga


class BaseProvider:
    info: ProviderInfo = {"name": "Base", "url": "", "types": [], "site_type": ""}
    infos: dict[str, ProviderInfo] = {}
    _cache_ttl = 30 * 24 * 60 * 60

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if hasattr(cls, 'provide') and callable(cls.provide):
            cls.provide = _instrumented_provide(cls.provide)

    def __init__(self):
        self._cache: TTLCache = TTLCache(1e4, self._cache_ttl)
        self.session: Session = Session()
        self.logger: logging.Logger = logging.getLogger(self.info["name"] + "DataProvider")
