import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any, ClassVar, Type, TypedDict

from redis.asyncio import Redis

from ris.provider_engines import ProviderData
from ris.redis_data_types import RedisStorageDataTypesMixin


@dataclass
class RedisDataSet:
    __keys__: ClassVar[dict[str, str]] = {}
    __redis_storage__: "RedisStorage | None" = field(default=None, init=False)

    async def save(self, keys: list[str] = []) -> None:
        if self.__redis_storage__ is None:
            raise RuntimeError("Redis storage not set")
        await self.__redis_storage__.save_data_set(self, keys)

    # fmt: off
    @classmethod
    async def fetch[T: RedisDataSet](
    # fmt: on
        cls: Type[T],  # type: ignore[name-defined]
        redis_storage: "RedisStorage",
        fill_keys: list[str] = [],
        **kwargs: Any,
    ) -> T:  # type: ignore[name-defined]
        return await redis_storage.retrieve_data_set(cls, fill_keys, **kwargs)


class RedisCacheStatsEntry(TypedDict):
    entries: int
    memory: int | float


class RedisCacheStats(TypedDict):
    provider_data: RedisCacheStatsEntry
    provider_data_image_link: RedisCacheStatsEntry
    not_found: RedisCacheStatsEntry
    total: RedisCacheStatsEntry


class RedisStorage(RedisStorageDataTypesMixin):
    def __init__(self, redis_client: Redis):
        """Redis storage

        Args:
            redis_client (Redis): Redis client
        """
        self.redis_client = redis_client
        self.logger = logging.getLogger("ris:redis")
        self.logger.setLevel(logging.DEBUG)

    ### Redis Data Sets ###

    async def retrieve_data_set[T: RedisDataSet](self, _class: Type[T], fill_keys: list[str] = [], **kwargs: Any) -> T:  # type: ignore[name-defined]
        if missing_keys := (set(fill_keys) - set(_class.__keys__.keys())):
            raise RuntimeError(f"Key not found in __keys__ in {_class=} : {missing_keys}")
        prepared_keys = {
            attr_name: redis_key.format(**kwargs)
            for attr_name, redis_key in _class.__keys__.items()
            if not fill_keys or attr_name in fill_keys
        }
        values = {
            attr_name: value
            for attr_name, value in zip(prepared_keys.keys(), await self.mget(list(prepared_keys.values())))
            if value is not None
        }
        kwargs.update(values)
        obj = _class(**kwargs)
        setattr(obj, "__redis_storage__", self)
        return obj

    async def save_data_set(self, data_set: RedisDataSet, keys: list[str] = []) -> None:
        if missing_keys := (set(keys) - set(data_set.__keys__.keys())):
            raise RuntimeError(f"Key not found in __keys__ in {data_set.__class__=} : {missing_keys}")
        for attr_name, redis_key in data_set.__keys__.items():
            if keys and attr_name not in keys:
                continue
            await self.set(redis_key.format(**data_set.__dict__), getattr(data_set, attr_name))

    ### Provider Data Cache ###

    _provider_data_key = "ris:sj:provider_data:{provider_id}"
    _provider_data_image_link_key = "ris:xs:provider_data_image_link:{image_id}"
    _not_found_key = "ris:xs:not_found"

    async def cache_provider_data(self, image_id: str, data: ProviderData) -> None:
        serialized_result: str = data.to_json()
        await self.redis_client.set(self._provider_data_key.format(provider_id=data.provider_id), serialized_result)
        await self.redis_client.sadd(self._provider_data_image_link_key.format(image_id=image_id), data.provider_id)  # type: ignore[misc]

    async def get_cached_provider_data(self, *provider_ids: str) -> list[ProviderData]:
        if not provider_ids:
            return []
        keys: list[str] = [self._provider_data_key.format(provider_id=key) for key in provider_ids]
        return [ProviderData.from_json(data) for data in await self.redis_client.mget(keys) if data is not None]

    async def get_cached_provider_data_by_image(self, image_id: str) -> list[ProviderData]:
        keys: set[str] = await self.redis_client.smembers(self._provider_data_image_link_key.format(image_id=image_id))  # type: ignore[misc]
        return await self.get_cached_provider_data(*keys)

    async def mark_image_as_not_found(self, image_id: str) -> None:
        await self.redis_client.sadd(self._not_found_key, image_id)  # type: ignore[misc]

    async def is_image_marked_as_not_found(self, image_id: str) -> bool:
        return bool(await self.redis_client.sismember(self._not_found_key, image_id))  # type: ignore[misc]

    ## Provider Data Cache Management ##

    async def clear_provider_data_cache(self) -> int:
        if keys := await self.redis_client.keys(self._provider_data_image_link_key.format(image_id="*")):
            await self.redis_client.delete(*keys)
        if keys := await self.redis_client.keys(self._provider_data_key.format(provider_id="*")):
            await self.redis_client.delete(*keys)
            return len(keys)
        return 0

    async def clear_not_found_cache(self) -> int:
        total: int = await self.redis_client.scard(self._not_found_key)  # type: ignore[misc]
        await self.redis_client.delete(self._not_found_key)
        return total

    async def _memory_usage_approximation(self, keys: list[str]) -> int | float:
        sample_size = min(len(keys), 20)
        if sample_size == 0:
            return 0
        subset = random.sample(keys, sample_size)
        subset_memory = sum(await asyncio.gather(*[self.redis_client.memory_usage(key) for key in subset]))
        return subset_memory * (len(keys) / sample_size)

    async def get_cache_stats(self) -> RedisCacheStats:
        provider_data_keys: list[str] = []
        async for key in self.redis_client.scan_iter(self._provider_data_image_link_key.format(image_id="*")):
            provider_data_keys.append(key)

        total_provider_data_memory_approximation = await self._memory_usage_approximation(provider_data_keys)

        provider_data_image_link_keys: list[str] = []
        async for key in self.redis_client.scan_iter(self._provider_data_key.format(provider_id="*")):
            provider_data_image_link_keys.append(key)

        total_provider_data_image_link_memory_approximation = await self._memory_usage_approximation(
            provider_data_image_link_keys
        )

        total_not_found_entries: int = await self.redis_client.scard(self._not_found_key)  # type: ignore[misc]
        total_not_found_memory: int = await self.redis_client.memory_usage(self._not_found_key) or 0

        return {
            "provider_data": {
                "entries": len(provider_data_keys),
                "memory": total_provider_data_memory_approximation,
            },
            "provider_data_image_link": {
                "entries": len(provider_data_image_link_keys),
                "memory": total_provider_data_image_link_memory_approximation,
            },
            "not_found": {
                "entries": total_not_found_entries,
                "memory": total_not_found_memory,
            },
            "total": {
                "entries": len(provider_data_keys) + len(provider_data_image_link_keys) + total_not_found_entries,
                "memory": (
                    total_provider_data_memory_approximation
                    + total_provider_data_image_link_memory_approximation
                    + total_not_found_memory
                ),
            },
        }

    ### User Data ###

    _active_users_key = "ris:xi:users"
    _user_search_count_key = "ris:si:user:{user_id}:search_count"
    _total_search_count_key = "ris:si:total:search"

    async def get_users(self) -> set[int]:
        return await self.get(self._active_users_key, set())  # type: ignore[return-value, arg-type]

    async def get_total_user_count(self) -> int:
        return await self.redis_client.scard(self._active_users_key)  # type: ignore[misc, no-any-return]

    async def incr_user_search_count(self, user_id: int) -> None:
        await self.redis_client.sadd(self._active_users_key, user_id)  # type: ignore[misc]
        await self.redis_client.incr(self._user_search_count_key.format(user_id=user_id))
        await self.redis_client.incr(self._total_search_count_key)

    async def get_user_search_count(self, user_id: int) -> int:
        return await self.get(self._user_search_count_key.format(user_id=user_id), 0)  # type: ignore[return-value]

    async def get_total_search_count(self) -> int:
        return await self.get(self._total_search_count_key, 0)  # type: ignore[return-value]
