"""Async-aware cache decorators compatible with cachetools TTLCache."""

from __future__ import annotations

import contextlib
from functools import partial, wraps

from cachetools.keys import hashkey


def async_cached(cache, key=hashkey):
    """Like ``cachetools.cached`` but for async functions."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            k = key(*args, **kwargs)
            try:
                return cache[k]
            except KeyError:
                pass
            result = await func(*args, **kwargs)
            with contextlib.suppress(ValueError):
                cache[k] = result
            return result

        wrapper.cache = cache  # type: ignore[attr-defined]
        return wrapper

    return decorator


def async_cachedmethod(cache_getter, key=hashkey):
    """Like ``cachetools.cachedmethod`` but for async methods."""

    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            cache = cache_getter(self)
            k = key(*args, **kwargs)
            try:
                return cache[k]
            except KeyError:
                pass
            result = await func(self, *args, **kwargs)
            with contextlib.suppress(ValueError):
                cache[k] = result
            return result

        return wrapper

    return decorator


def async_provider_cache(func):
    """Async version of ``provider_cache`` for data providers."""
    return async_cachedmethod(lambda self: self._cache, key=partial(hashkey, func.__qualname__))(func)
