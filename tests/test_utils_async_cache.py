"""Tests for reverse_image_search_bot.utils.async_cache."""

import pytest
from cachetools import TTLCache

from reverse_image_search_bot.utils.async_cache import (
    async_cached,
    async_cachedmethod,
    async_provider_cache,
)


@pytest.mark.asyncio
class TestAsyncCached:
    async def test_caches_result(self):
        cache = TTLCache(maxsize=100, ttl=300)
        call_count = 0

        @async_cached(cache)
        async def add(a, b):
            nonlocal call_count
            call_count += 1
            return a + b

        assert await add(1, 2) == 3
        assert await add(1, 2) == 3
        assert call_count == 1

    async def test_different_args_not_cached(self):
        cache = TTLCache(maxsize=100, ttl=300)
        call_count = 0

        @async_cached(cache)
        async def add(a, b):
            nonlocal call_count
            call_count += 1
            return a + b

        assert await add(1, 2) == 3
        assert await add(3, 4) == 7
        assert call_count == 2

    async def test_cache_exposed(self):
        cache = TTLCache(maxsize=100, ttl=300)

        @async_cached(cache)
        async def func(x):
            return x

        await func(1)
        assert func.cache is cache
        assert len(cache) == 1


@pytest.mark.asyncio
class TestAsyncCachedMethod:
    async def test_caches_method_result(self):
        call_count = 0

        class MyClass:
            def __init__(self):
                self._cache = TTLCache(maxsize=100, ttl=300)

            @async_cachedmethod(lambda self: self._cache)
            async def compute(self, x):
                nonlocal call_count
                call_count += 1
                return x * 2

        obj = MyClass()
        assert await obj.compute(5) == 10
        assert await obj.compute(5) == 10
        assert call_count == 1

    async def test_separate_instances_separate_caches(self):
        call_count = 0

        class MyClass:
            def __init__(self):
                self._cache = TTLCache(maxsize=100, ttl=300)

            @async_cachedmethod(lambda self: self._cache)
            async def compute(self, x):
                nonlocal call_count
                call_count += 1
                return x * 2

        a = MyClass()
        b = MyClass()
        assert await a.compute(5) == 10
        assert await b.compute(5) == 10
        assert call_count == 2


@pytest.mark.asyncio
class TestAsyncProviderCache:
    async def test_provider_cache_works(self):
        call_count = 0

        class Provider:
            def __init__(self):
                self._cache = TTLCache(maxsize=100, ttl=300)

            @async_provider_cache
            async def provide(self, item_id):
                nonlocal call_count
                call_count += 1
                return {"id": item_id}, {}

        p = Provider()
        r1 = await p.provide(123)
        r2 = await p.provide(123)
        assert r1 == r2
        assert call_count == 1

        # Different arg is not cached
        await p.provide(456)
        assert call_count == 2
