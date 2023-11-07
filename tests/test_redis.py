from dataclasses import dataclass
from typing import Any, AsyncGenerator, ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from ris.provider_engines import ProviderData
from ris.redis import RedisDataSet, RedisStorage


class RedisStorageImpl(RedisStorage):
    redis_client: MagicMock  # Set so that mypy doesn't complain


@dataclass
class MockRedisDataSet(RedisDataSet):
    __keys__: ClassVar[dict[str, str]] = {
        "example_value": "ris:ss:example:{example_id}",
        "additional_value": "ris:ss:additional:{example_id}",
    }

    example_id: int
    example_value: str = ""
    additional_value: str = ""


class TestRedisDataSet:
    @pytest.fixture(autouse=True)
    async def setup_method(self, mock_redis_client: AsyncMock) -> None:
        """Setup method that's called before each test function."""
        self.redis = RedisStorageImpl(mock_redis_client)

    async def test_save(self) -> None:
        data_set = MockRedisDataSet(example_id=123, example_value="value")
        setattr(data_set, "__redis_storage__", self.redis)

        self.redis.save_data_set = AsyncMock()  # type: ignore[method-assign]

        await data_set.save()

        self.redis.save_data_set.assert_awaited_with(data_set, [])
        self.redis.save_data_set.redis_client.set.await_count == 1

    async def test_save_with_keys(self) -> None:
        data_set = MockRedisDataSet(example_id=123, example_value="value")
        setattr(data_set, "__redis_storage__", self.redis)

        self.redis.save_data_set = AsyncMock()  # type: ignore[method-assign]

        await data_set.save(["example_value"])

        self.redis.save_data_set.assert_awaited_with(data_set, ["example_value"])
        self.redis.save_data_set.redis_client.set.await_count == 1

    async def test_save_with_no_redis_storage_set(self) -> None:
        data_set = MockRedisDataSet(example_id=123, example_value="value")

        with pytest.raises(RuntimeError):
            await data_set.save(["example_value"])

    async def test_fetch(self) -> None:
        self.redis.retrieve_data_set = AsyncMock()  # type: ignore[method-assign]
        self.redis.retrieve_data_set.return_value = MockRedisDataSet(example_id=123, example_value="value")

        result = await MockRedisDataSet.fetch(self.redis, example_id=123, fill_keys=["additional_value"])

        self.redis.retrieve_data_set.assert_awaited_with(MockRedisDataSet, ["additional_value"], example_id=123)
        assert isinstance(result, MockRedisDataSet)


class TestRedisStorage:
    @pytest.fixture(autouse=True)
    async def setup_method(self, mock_redis_client: AsyncMock) -> None:
        """Setup method that's called before each test function."""
        self.redis = RedisStorageImpl(mock_redis_client)

    ### Redis Data Sets ###

    async def test_retrieve_data_set(self) -> None:
        self.redis.redis_client.mget.return_value = ["value", None]
        mock_dataset_cls = MockRedisDataSet
        expected_keys = ["ris:ss:example:123", "ris:ss:additional:123"]

        result = await self.redis.retrieve_data_set(mock_dataset_cls, example_id=123)

        self.redis.redis_client.mget.assert_awaited_with(expected_keys)
        assert isinstance(result, MockRedisDataSet)
        assert result.example_value == "value"
        assert result.additional_value == ""  # Use default value defined in dataclass if key is not found

    async def test_retrieve_data_set_with_missing_keys(self) -> None:
        with pytest.raises(RuntimeError):
            await self.redis.retrieve_data_set(MockRedisDataSet, example_id=123, fill_keys=["nonexistent_key"])

    async def test_save_data_set(self) -> None:
        data_set = MockRedisDataSet(example_id=123, example_value="value")
        expected_key = "ris:ss:additional:123"
        expected_value = ""

        await self.redis.save_data_set(data_set)

        self.redis.redis_client.set.assert_awaited_with(expected_key, expected_value)
        self.redis.redis_client.set.await_count == 2

    async def test_save_data_set_with_missing_keys(self) -> None:
        data_set = MockRedisDataSet(example_id=123, example_value="value")

        with pytest.raises(RuntimeError):
            await self.redis.save_data_set(data_set, keys=["nonexistent_key"])

    async def test_retrieve_data_set_with_fill_keys(self) -> None:
        self.redis.mget = AsyncMock()  # type: ignore[method-assign]
        self.redis.mget.return_value = ["additional_value"]

        mock_dataset_cls = MockRedisDataSet
        expected_keys = {"additional_value": "ris:ss:additional:123"}

        result = await self.redis.retrieve_data_set(mock_dataset_cls, example_id=123, fill_keys=["additional_value"])

        self.redis.mget.assert_awaited_with(list(expected_keys.values()))
        assert isinstance(result, MockRedisDataSet)
        assert (
            result.example_value == ""
        )  # Use default value defined in dataclass if key is not requested (not in fill_keys)
        assert result.additional_value == "additional_value"

    async def test_retrieve_data_set_with_kwargs(self) -> None:
        self.redis.mget = AsyncMock()  # type: ignore[method-assign]
        self.redis.mget.return_value = [None, "additional_value"]

        mock_dataset_cls = MockRedisDataSet
        expected_keys = {"example": "ris:ss:example:123", "additional": "ris:ss:additional:123"}

        result = await self.redis.retrieve_data_set(mock_dataset_cls, example_id=123, example_value="predefined")

        self.redis.mget.assert_awaited_with(list(expected_keys.values()))
        assert isinstance(result, MockRedisDataSet)
        assert result.example_value == "predefined"
        assert result.additional_value == "additional_value"

    async def test_save_data_set_with_keys(self) -> None:
        data_set = MockRedisDataSet(example_id=123, example_value="value", additional_value="additional")
        expected_key = "ris:ss:example:123"
        expected_value = "value"
        keys = ["example_value"]

        self.redis.set = AsyncMock()  # type: ignore[method-assign]

        await self.redis.save_data_set(data_set, keys=keys)

        self.redis.set.assert_awaited_with(expected_key, expected_value)
        self.redis.set.await_count == 1

    ### Provider Data ###

    async def test_cache_provider_data(self, provider_data: ProviderData) -> None:
        image_id = "123456"
        serialized_result = provider_data.to_json()

        await self.redis.cache_provider_data(image_id, provider_data)
        self.redis.redis_client.set.assert_awaited_with(
            f"ris:sj:provider_data:{provider_data.provider_id}", serialized_result
        )
        self.redis.redis_client.sadd.assert_awaited_with(
            f"ris:xs:provider_data_image_link:{image_id}", provider_data.provider_id
        )

    async def test_get_cached_provider_data(self, provider_data_list: list[ProviderData]) -> None:
        provider_ids = [data.provider_id for data in provider_data_list]
        keys = [f"ris:sj:provider_data:{provider_id}" for provider_id in provider_ids]
        json_data = [data.to_json() for data in provider_data_list]

        self.redis.redis_client.mget.return_value = json_data
        result: list[ProviderData] = await self.redis.get_cached_provider_data(*provider_ids)

        self.redis.redis_client.mget.assert_awaited_with(keys)
        assert all(isinstance(item, ProviderData) for item in result)
        assert len(result) == len(provider_ids)

    async def test_get_cached_provider_data_by_image(self, provider_data_list: list[ProviderData]) -> None:
        image_id = "123456"
        provider_ids = {data.provider_id for data in provider_data_list}
        json_data = [data.to_json() for data in provider_data_list]

        self.redis.redis_client.smembers.return_value = provider_ids
        self.redis.redis_client.mget.return_value = json_data

        result = await self.redis.get_cached_provider_data_by_image(image_id)

        self.redis.redis_client.smembers.assert_awaited_with(f"ris:xs:provider_data_image_link:{image_id}")
        self.redis.redis_client.mget.assert_awaited_with(
            [f"ris:sj:provider_data:{provider_id}" for provider_id in provider_ids]
        )
        assert all(isinstance(item, ProviderData) for item in result)
        assert len(result) == len(provider_ids)

    async def test_mark_image_as_not_found(self) -> None:
        image_id = "image_not_found"
        await self.redis.mark_image_as_not_found(image_id)
        self.redis.redis_client.sadd.assert_awaited_with("ris:xs:not_found", image_id)

    async def test_is_image_marked_as_not_found(self) -> None:
        image_id = "image_not_found"

        self.redis.redis_client.sismember.return_value = 1
        result = await self.redis.is_image_marked_as_not_found(image_id)
        self.redis.redis_client.sismember.assert_awaited_with("ris:xs:not_found", image_id)
        assert result is True

    ## Provider Data Cache Management ##

    async def test_clear_provider_data_cache(self) -> None:
        self.redis.redis_client.keys = AsyncMock(
            side_effect=[
                ["key1", "key2"],  # First call for image link keys
                ["key3", "key4"],  # Second call for provider data keys
            ]
        )
        self.redis.redis_client.delete = AsyncMock()

        # Call clear_provider_data_cache
        num_deleted = await self.redis.clear_provider_data_cache()

        # Assertions
        assert num_deleted == 2  # Should return the number of provider data keys deleted
        assert self.redis.redis_client.delete.call_count == 2
        self.redis.redis_client.keys.assert_any_call(self.redis._provider_data_image_link_key.format(image_id="*"))
        self.redis.redis_client.keys.assert_any_call(self.redis._provider_data_key.format(provider_id="*"))

    async def test_clear_not_found_cache(self) -> None:
        self.redis.redis_client.scard = AsyncMock(return_value=3)
        self.redis.redis_client.delete = AsyncMock()

        # Call clear_not_found_cache
        num_cleared = await self.redis.clear_not_found_cache()

        # Assertions
        assert num_cleared == 3  # Should return the total number of not found entries
        self.redis.redis_client.scard.assert_awaited_with(self.redis._not_found_key)
        self.redis.redis_client.delete.assert_awaited_with(self.redis._not_found_key)

    async def test_get_cache_stats(self) -> None:
        async def generator_mock(*_: Any, **__: Any) -> AsyncGenerator[Any, None]:
            yield ["key1", "key2"]
            yield ["key3", "key4"]

        self.redis.redis_client.scan_iter = generator_mock

        self.redis._memory_usage_approximation = AsyncMock(side_effect=[100, 200])  # type: ignore[method-assign]
        self.redis.redis_client.scard = AsyncMock(return_value=3)
        self.redis.redis_client.memory_usage = AsyncMock(return_value=10)

        # Call get_cache_stats
        stats = await self.redis.get_cache_stats()

        # Assertions
        assert stats["provider_data"]["entries"] == 2
        assert stats["provider_data"]["memory"] == 100
        assert stats["provider_data_image_link"]["entries"] == 2
        assert stats["provider_data_image_link"]["memory"] == 200
        assert stats["not_found"]["entries"] == 3
        assert stats["not_found"]["memory"] == 10
        assert stats["total"]["entries"] == 2 + 2 + 3
        assert stats["total"]["memory"] == 100 + 200 + 10

    async def test_memory_usage_approximation_many_keys(self) -> None:
        keys = [f"ris:ss:example:{i}" for i in range(100)]
        self.redis.redis_client.memory_usage = AsyncMock(return_value=100)
        result = await self.redis._memory_usage_approximation(keys)
        assert result == 100 * 100
        assert self.redis.redis_client.memory_usage.await_count == 20

    async def test_memory_usage_approximation_few_keys(self) -> None:
        keys = [f"ris:ss:example:{i}" for i in range(10)]
        self.redis.redis_client.memory_usage = AsyncMock(return_value=100)
        result = await self.redis._memory_usage_approximation(keys)
        assert result == 100 * 10
        assert self.redis.redis_client.memory_usage.await_count == 10

    async def test_memory_usage_approximation_no_keys(self) -> None:
        keys: list[str] = []
        self.redis.redis_client.memory_usage = AsyncMock(return_value=100)
        result = await self.redis._memory_usage_approximation(keys)
        assert result == 0
        assert self.redis.redis_client.memory_usage.await_count == 0

    ### User Data ###

    async def test_get_users(self) -> None:
        self.redis.get = AsyncMock()  # type: ignore[method-assign]
        self.redis.get.return_value = {1, 2, 3}

        result = await self.redis.get_users()
        self.redis.get.assert_awaited_with(self.redis._active_users_key, set())
        assert result == {1, 2, 3}

    async def test_get_total_user_count(self) -> None:
        self.redis.redis_client.scard = AsyncMock()
        self.redis.redis_client.scard.return_value = 10
        result = await self.redis.get_total_user_count()
        self.redis.redis_client.scard.assert_awaited_with(self.redis._active_users_key)
        assert result == 10

    async def test_incr_user_search_count(self) -> None:
        user_id = 123
        self.redis.redis_client.incr = AsyncMock()
        await self.redis.incr_user_search_count(user_id)
        self.redis.redis_client.sadd.assert_awaited_with(self.redis._active_users_key, user_id)
        self.redis.redis_client.incr.assert_any_await(self.redis._user_search_count_key.format(user_id=user_id))
        self.redis.redis_client.incr.assert_any_await(self.redis._total_search_count_key)

    async def test_get_user_search_count(self) -> None:
        user_id = 123
        self.redis.get = AsyncMock()  # type: ignore[method-assign]
        self.redis.get.return_value = 5
        result = await self.redis.get_user_search_count(user_id)
        self.redis.get.assert_awaited_with(self.redis._user_search_count_key.format(user_id=user_id), 0)
        assert result == 5

    async def test_get_total_search_count(self) -> None:
        self.redis.get = AsyncMock()  # type: ignore[method-assign]
        self.redis.get.return_value = 42
        result = await self.redis.get_total_search_count()
        self.redis.get.assert_awaited_with(self.redis._total_search_count_key, 0)
        assert result == 42
