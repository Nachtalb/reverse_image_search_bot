import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from ris.redis_data_types import RedisStorageDataTypesMixin


class RedisStorageImpl(RedisStorageDataTypesMixin):
    redis_client: MagicMock


class TestRedisStorageDateTypesMixin:
    @pytest.fixture(autouse=True)
    async def setup_method(self, mock_redis_client: AsyncMock) -> None:
        """Setup method that's called before each test function."""
        self.redis = RedisStorageImpl()
        self.redis.redis_client = mock_redis_client

    async def test_set_str(self) -> None:
        await self.redis.set("test_key_str", "test_value")
        self.redis.redis_client.set.assert_awaited_with("ris:s:test_key_str", "test_value")

    async def test_get_str(self) -> None:
        self.redis.redis_client.get.return_value = "test_value"
        result = await self.redis.get("ris:s:test_key_str")
        assert result == "test_value"

    async def test_set_int(self) -> None:
        await self.redis.set("test_key_int", 123)
        self.redis.redis_client.set.assert_awaited_with("ris:i:test_key_int", "123")

    async def test_get_int(self) -> None:
        self.redis.redis_client.get.return_value = "123"
        result = await self.redis.get("ris:i:test_key_int")
        assert result == 123

    async def test_set_float(self) -> None:
        await self.redis.set("test_key_float", 12.34)
        self.redis.redis_client.set.assert_awaited_with("ris:f:test_key_float", "12.34")

    async def test_get_float(self) -> None:
        self.redis.redis_client.get.return_value = "12.34"
        result = await self.redis.get("ris:f:test_key_float")
        assert result == 12.34

    async def test_set_bool_true(self) -> None:
        await self.redis.set("test_key_bool_true", True)
        self.redis.redis_client.set.assert_awaited_with("ris:b:test_key_bool_true", "1")

    async def test_get_bool_true(self) -> None:
        self.redis.redis_client.get.return_value = "1"
        result = await self.redis.get("ris:b:test_key_bool_true")
        assert result is True

    async def test_set_bool_false(self) -> None:
        await self.redis.set("test_key_bool_false", False)
        self.redis.redis_client.set.assert_awaited_with("ris:b:test_key_bool_false", "0")

    async def test_get_bool_false(self) -> None:
        self.redis.redis_client.get.return_value = "0"
        result = await self.redis.get("ris:b:test_key_bool_false")
        assert result is False

    async def test_set_dict(self) -> None:
        test_dict = {"key": "value"}
        await self.redis.set("test_key_dict", test_dict)
        json_data = json.dumps(test_dict)
        self.redis.redis_client.set.assert_awaited_with("ris:j:test_key_dict", json_data)

    async def test_get_dict(self) -> None:
        test_dict = {"key": "value"}
        self.redis.redis_client.get.return_value = json.dumps(test_dict)
        result = await self.redis.get("ris:j:test_key_dict")
        assert result == test_dict

    async def test_set_list(self) -> None:
        test_list = ["one", "two", "three"]
        await self.redis.set("test_key_list", test_list)
        json_data = json.dumps(test_list)
        self.redis.redis_client.set.assert_awaited_with("ris:j:test_key_list", json_data)

    async def test_get_list(self) -> None:
        test_list = ["one", "two", "three"]
        self.redis.redis_client.get.return_value = json.dumps(test_list)
        result = await self.redis.get("ris:j:test_key_list")
        assert result == test_list

    async def test_set_set_str(self) -> None:
        test_set = {"one", "two", "three"}
        await self.redis.set("test_key_set_str", test_set, set_type=str)
        self.redis.redis_client.sadd.assert_awaited_once()
        assert self.redis.redis_client.sadd.await_args[0][0] == "ris:xs:test_key_set_str"
        assert set(self.redis.redis_client.sadd.await_args[0][1:]) == test_set

    async def test_get_set_str(self) -> None:
        test_set = {"one", "two", "three"}
        self.redis.redis_client.smembers.return_value = test_set
        result = await self.redis.get("ris:xs:test_key_set_str")
        assert result == test_set

    async def test_set_set_int(self) -> None:
        test_set = {1, 2, 3}
        await self.redis.set("test_key_set_int", test_set, set_type=int)
        self.redis.redis_client.sadd.assert_awaited_once()
        assert self.redis.redis_client.sadd.await_args[0][0] == "ris:xi:test_key_set_int"
        assert set(self.redis.redis_client.sadd.await_args[0][1:]) == set(map(str, test_set))

    async def test_get_set_int(self) -> None:
        test_set = {"1", "2", "3"}
        self.redis.redis_client.smembers.return_value = test_set
        result = await self.redis.get("ris:xi:test_key_set_int")
        assert result == {1, 2, 3}

    async def test_set_set_float(self) -> None:
        test_set = {1.1, 2.2, 3.3}
        await self.redis.set("test_key_set_float", test_set, set_type=float)
        self.redis.redis_client.sadd.assert_awaited_once()
        assert self.redis.redis_client.sadd.await_args[0][0] == "ris:xf:test_key_set_float"
        assert set(self.redis.redis_client.sadd.await_args[0][1:]) == set(map(str, test_set))

    async def test_get_set_float(self) -> None:
        test_set = {"1.1", "2.2", "3.3"}
        self.redis.redis_client.smembers.return_value = test_set
        result = await self.redis.get("ris:xf:test_key_set_float")
        assert result == {1.1, 2.2, 3.3}

    async def test_set_set_bool(self) -> None:
        test_set = {True, False}
        await self.redis.set("test_key_set_bool", test_set, set_type=bool)
        self.redis.redis_client.sadd.assert_awaited_once()
        assert self.redis.redis_client.sadd.await_args[0][0] == "ris:xb:test_key_set_bool"
        assert set(self.redis.redis_client.sadd.await_args[0][1:]) == {str(int(i)) for i in test_set}

    async def test_get_set_bool(self) -> None:
        test_set = {"1", "0"}
        self.redis.redis_client.smembers.return_value = test_set
        result = await self.redis.get("ris:xb:test_key_set_bool")
        assert result == {True, False}

    async def test_get_key_not_found_without_default(self) -> None:
        # Test that KeyError is raised when the key is not found and no default is provided
        self.redis.redis_client.keys.return_value = []
        with pytest.raises(KeyError) as exc_info:
            await self.redis.get("nonexistent_key")
        assert "Key not found" in str(exc_info.value)

    async def test_get_key_not_found_with_default(self) -> None:
        # Test that default is returned when the key is not found
        default_value = "default"
        self.redis.redis_client.keys.return_value = []
        result = await self.redis.get("nonexistent_key", default=default_value)
        assert result == default_value

    async def test_get_invalid_key_format(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            await self.redis.get("ris:invalid_key_format")
        assert "Invalid key format" in str(exc_info.value)

    async def test_get_set_with_incorrect_inner_type(self) -> None:
        # Test getting a set with an incorrect inner type (e.g., expecting int, getting str)
        self.redis.redis_client.smembers.return_value = {"not_an_int", "also_not_an_int"}
        with pytest.raises(ValueError):
            await self.redis.get("ris:xi:test_key_set_int")

    async def test_get_with_incorrect_data_type(self) -> None:
        # Test that a ValueError is raised when the data type does not match the expected type
        self.redis.redis_client.get.return_value = "not_a_bool"
        with pytest.raises(ValueError):
            await self.redis.get("ris:b:test_key_bool")

    async def test_set_unsupported_type(self) -> None:
        # Test that a TypeError is raised when trying to set an unsupported type
        with pytest.raises(TypeError):
            await self.redis.set("test_key_unsupported", object())  # type: ignore[arg-type]

    async def test_keys_with_valid_custom_pattern(self) -> None:
        pattern = "custom:*"
        expected_keys = ["ris:s:custom:1", "ris:i:custom:2"]
        self.redis.redis_client.keys.return_value = expected_keys
        result = await self.redis.keys(pattern)
        self.redis.redis_client.keys.assert_awaited_with("ris:[sifbjx][sifb]?:custom:*")
        assert result == expected_keys

    async def test_keys_without_ris_prefix(self) -> None:
        pattern = "key_without_prefix"
        expected_keys = ["ris:s:key_without_prefix"]
        self.redis.redis_client.keys.return_value = expected_keys
        result = await self.redis.keys(pattern)
        self.redis.redis_client.keys.assert_awaited_with(f"ris:[sifbjx][sifb]?:{pattern}")
        assert result == expected_keys

    async def test_check_key_format_valid(self) -> None:
        key = "ris:s:valid_key"
        key_info = self.redis._check_key_format(key)
        assert key_info is not None
        data_type, key_name = key_info
        assert data_type == "s"
        assert key_name == "valid_key"

    async def test_check_key_format_invalid(self) -> None:
        key = "ris:invalid_format_key"
        with pytest.raises(ValueError) as exc_info:
            self.redis._check_key_format(key)
        assert "Invalid key format" in str(exc_info.value)

    async def test_check_key_format_without_prefix(self) -> None:
        key = "key_without_prefix"
        result = self.redis._check_key_format(key)
        assert result is None

    async def test_serialize_bool(self) -> None:
        assert self.redis._serialize(True, "ris:b:key") == "1"

    async def test_serialize_int(self) -> None:
        assert self.redis._serialize(1, "ris:i:key") == "1"

    async def test_serialize_float(self) -> None:
        assert self.redis._serialize(1.0, "ris:f:key") == "1.0"

    async def test_serialize_set_bool(self) -> None:
        assert self.redis._serialize({True, False}, "ris:xb:key") == {"1", "0"}

    async def test_serialize_set_int(self) -> None:
        assert self.redis._serialize({1, 2}, "ris:xi:key") == {"1", "2"}

    async def test_serialize_set_float(self) -> None:
        assert self.redis._serialize({1.0, 2.0}, "ris:xf:key") == {"1.0", "2.0"}

    async def test_serialize_list(self) -> None:
        list_value = ["one", "two", "three"]
        assert self.redis._serialize(list_value, "ris:j:key") == json.dumps(list_value)

    async def test_serialize_dict(self) -> None:
        dict_value = {"key": "value"}
        assert self.redis._serialize(dict_value, "ris:j:key") == json.dumps(dict_value)

    async def test_serialize_invalid_key(self) -> None:
        with pytest.raises(ValueError):
            self.redis._serialize("value", "invalid:key")

    async def test_deserialize_int(self) -> None:
        assert self.redis._deserialize("1", "ris:i:key") == 1

    async def test_deserialize_float(self) -> None:
        assert self.redis._deserialize("1.0", "ris:f:key") == 1.0

    async def test_deserialize_bool(self) -> None:
        assert self.redis._deserialize("1", "ris:b:key") is True

    async def test_deserialize_dict(self) -> None:
        json_value = '{"key": "value"}'
        assert self.redis._deserialize(json_value, "ris:j:key") == {"key": "value"}

    async def test_deserialize_set_int(self) -> None:
        assert self.redis._deserialize({"1", "2"}, "ris:xi:key") == {1, 2}

    async def test_deserialize_set_bool(self) -> None:
        assert self.redis._deserialize({"1", "0"}, "ris:xb:key") == {True, False}

    async def test_deserialize_invalid_key(self) -> None:
        with pytest.raises(ValueError):
            self.redis._deserialize("value", "invalid:key")

    async def test_mget_with_valid_keys(self) -> None:
        keys = ["ris:s:key1", "ris:xi:key2"]
        self.redis.redis_client.pipeline.return_value.execute.return_value = [{"1", "2"}, {"3", "4"}]
        self.redis.redis_client.mget.return_value = ["value1", "value2"]
        results = await self.redis.mget(keys)
        # Ensure that the pipeline is used for set keys
        self.redis.redis_client.pipeline.assert_called_once()
        self.redis.redis_client.pipeline.return_value.execute.assert_called_once()
        # Ensure that mget is called for string keys
        self.redis.redis_client.mget.assert_called_once_with(["ris:s:key1"])
        assert results == ["value1", {1, 2}]

    async def test_mget_with_mixed_valid_invalid_keys(self) -> None:
        keys = ["ris:s:key1", "invalid:key2"]
        self.redis.redis_client.pipeline.return_value.execute.return_value = [{"1", "2"}]
        with pytest.raises(ValueError):
            await self.redis.mget(keys)

    async def test_mget_with_all_set_keys(self) -> None:
        keys = ["ris:xi:key1", "ris:xi:key2"]
        self.redis.redis_client.pipeline.return_value.execute.return_value = [{"1", "2"}, {"3", "4"}]
        results = await self.redis.mget(keys)
        # Ensure that the pipeline is used for all set keys
        self.redis.redis_client.pipeline.assert_called_once()
        self.redis.redis_client.pipeline.return_value.execute.assert_called_once()
        assert results == [{1, 2}, {3, 4}]

    async def test_mget_with_all_string_keys(self) -> None:
        keys = ["ris:s:key1", "ris:s:key2"]
        self.redis.redis_client.mget.return_value = ["value1", "value2"]
        results = await self.redis.mget(keys)
        # Ensure that mget is called for all string keys
        self.redis.redis_client.mget.assert_called_once_with(keys)
        assert results == ["value1", "value2"]

    async def test_mget_dict(self) -> None:
        keys = ["ris:s:key1", "ris:i:key2"]
        expected_values = ["value1", 42]
        self.redis.mget = AsyncMock(return_value=expected_values)  # type: ignore[method-assign]
        self.redis.mget.return_value = expected_values
        result = await self.redis.mget_dict(keys)
        self.redis.mget.assert_awaited_with(keys)
        assert result == {"ris:s:key1": "value1", "ris:i:key2": 42}

    async def test_mget_dict_short(self) -> None:
        keys = ["ris:s:key1", "ris:i:key2"]
        expected_values = ["value1", 42]
        self.redis.mget = AsyncMock(return_value=expected_values)  # type: ignore[method-assign]
        self.redis.mget.return_value = expected_values
        result = await self.redis.mget_dict_short(keys)
        self.redis.mget.assert_awaited_with(keys)
        assert result == {"key1": "value1", "key2": 42}
