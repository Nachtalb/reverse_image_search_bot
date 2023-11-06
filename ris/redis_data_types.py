import json
import re
from collections.abc import Collection
from typing import Any, Callable, Type

from redis.asyncio import Redis

DATA_TYPES_CHECK = (str, int, float, bool, dict, list, set)
DATA_TYPES = str | int | float | bool | dict | list | set[str] | set[int] | set[float] | set[bool]

CONTAINER_MAP = {
    str: "s",
    set: "x",
}
TYPE_MAP = {
    str: "s",
    int: "i",
    float: "f",
    bool: "b",
    dict: "j",  # As JSON
    list: "j",  # As JSON
}

CONTAINER_MAP_REVERSE = {v: k for k, v in CONTAINER_MAP.items()}
TYPE_MAP_REVERSE = {v: k for k, v in TYPE_MAP.items()}

SERIALIZE_MAP: dict[str, Callable[[DATA_TYPES], str]] = {
    "s": str,
    "i": str,
    "f": str,
    "b": lambda x: str(int(x)),  # type: ignore[arg-type]
    "j": json.dumps,
}

DESERIALIZE_MAP: dict[str, Callable[[str], DATA_TYPES]] = {
    "s": str,
    "i": int,
    "f": float,
    "b": lambda x: bool(int(x)),
    "j": json.loads,
}


class RedisStorageDataTypesMixin:
    redis_client: Redis

    # def __serialize[T](self, value: DATA_TYPES, key: str, _map: dict[str, Callable[[Any], T]]) -> T:  Better py3.12 syntax has no support in mypy yet :(
    def __serialize(self, value: DATA_TYPES, key: str, _map: dict[str, Callable[[Any], Any]]) -> Any:
        """Serialize value

        Args:
            value (DATA_TYPES): Value
            key (str): Key
            _map (dict[str, Callable[[Any], Any]]): Map

        Returns:
            Any: Serialized value
        """
        if not self._check_key_format(key):
            raise ValueError("Invalid key format, correct format is 'ris:[data_type]:[key]'")
        _, data_type, _ = key.split(":", 2)
        container, _type = tuple(data_type)

        if container == "x":
            fun = _map[_type]
            return {fun(val) for val in value}  # type: ignore[union-attr]
        return _map[_type](value)

    def _serialize(self, value: DATA_TYPES, key: str) -> str | set[str]:
        """Serialize value

        Args:
            value (DATA_TYPES): Value
            key (str): Key

        Returns:
            str | set[str]: Serialized value
        """
        return self.__serialize(value, key, SERIALIZE_MAP)  # type: ignore[no-any-return]

    def _deserialize(self, value: str | set[str], key: str) -> DATA_TYPES:
        """Deserialize value

        Args:
            value (str): Value
            key (str): Key

        Returns:
            DATA_TYPES: Deserialized value
        """
        return self.__serialize(value, key, DESERIALIZE_MAP)  # type: ignore[no-any-return]

    async def set(self, key: str, value: DATA_TYPES, set_type: Type[str | int | float | bool] = str) -> None:
        """Set that handles all supported data types

        Schema:
            ris:[data_type]:[key] = [value]
            data_type: .. see TYPE_MAP
            key: str
            value: .. see DATA_TYPES

        Args:
            key (str): Key
            value (DATA_TYPES): Value
            set_type (Type, optional): Set type. Defaults to str.
        """
        if not isinstance(value, DATA_TYPES_CHECK):
            raise TypeError(f"Value must be one of {DATA_TYPES}")

        if isinstance(value, set):
            if key_info := self._check_key_format(key):
                data_type, _ = key_info
                if data_type[0] != "x":
                    raise ValueError(f"Invalid key or value. Key defines '{data_type}' but value is not a set")
            else:
                data_type = "x" + TYPE_MAP[set_type]
                key = f"ris:{data_type}:{key}"

            value = self._serialize(value, key)

            current_set = await self.redis_client.smembers(key)  # type: ignore[misc]
            if to_remove := current_set - value:
                await self.redis_client.srem(key, *to_remove)  # type: ignore[misc]

            if to_add := value - current_set:
                await self.redis_client.sadd(key, *to_add)  # type: ignore[misc]
            return

        if not self._check_key_format(key):
            data_type = "s" + TYPE_MAP[type(value)]
            key = f"ris:{data_type}:{key}"

        value = self._serialize(value, key)
        await self.redis_client.set(key, value)  # type: ignore[arg-type]

    async def get(self, key: str, default: DATA_TYPES | None = None) -> DATA_TYPES | None:
        """Get that handles all supported data types

        Schema:
            ris:[data_type]:[key] = [value]
            data_type: .. see TYPE_MAP
            key: str
            value: .. see DATA_TYPES

        Args:
            key (str): Key

        Returns:
            DATA_TYPES: Value
        """
        if not self._check_key_format(key):
            keys = await self.keys(key)
            if not keys:
                return default
            key = keys[0]

        _, data_type, _ = key.split(":", 2)

        if data_type[0] == "x":
            if not await self.redis_client.exists(key):
                return default
            value = await self.redis_client.smembers(key)  # type: ignore[misc]
            return self._deserialize(value, key)

        value = await self.redis_client.get(key)
        if value is None:
            return default
        return self._deserialize(value, key)

    async def mget(self, keys: Collection[str], mark_non_existing_sets: bool = True) -> list[DATA_TYPES | None]:
        """Get multiple keys while handling all supported data types including sets

        Note:
            In comparison to get() this method does not accommodate not fully qualified keys. This means that
            keys must be in the format 'ris:[data_type]:[key]'. The reason for this is that, we'd have to search
            redis for every non fully qualified key to find the correct key. This is an easily avoidable overhead
            if the keys are already known.

        Args:
            keys (Collection[str]): Keys in the format 'ris:[data_type]:[key]'
            mark_non_existing_sets (bool, optional): If True, sets that do not exist will be marked as None in the result list. Defaults to True.

        Returns:
            list[DATA_TYPES]: Values

        Raises:
            ValueError: Invalid key format
        """
        set_keys: dict[int, str] = {}
        string_keys: dict[int, str] = {}
        for index, key in enumerate(keys):
            if key_info := self._check_key_format(key):
                if key_info[0][0] == "x":
                    set_keys[index] = key
                else:
                    string_keys[index] = key
            else:
                raise ValueError(f"Invalid {key=}format, correct format is 'ris:[data_type]:[key]'")

        values: dict[int, DATA_TYPES | None] = {}

        if set_keys:
            lua_script = """
            local results = {}
            for i, key in ipairs(KEYS) do
                if redis.call("EXISTS", key) == 1 then
                    results[i] = redis.call("SMEMBERS", key)
                else
                    results[i] = nil
                end
            end
            return results
            """
            result = await self.redis_client.eval(lua_script, len(set_keys), *set_keys.values())  # type: ignore[misc, arg-type]
            for (index, key), value in zip(set_keys.items(), result):
                if value is None and mark_non_existing_sets:
                    values[index] = None
                else:
                    values[index] = set() if value is None else self._deserialize(value, key)  # type: ignore[assignment]

        if string_keys:
            for (index, key), value in zip(
                string_keys.items(), await self.redis_client.mget(list(string_keys.values()))
            ):
                values[index] = None if value is None else self._deserialize(value, key)

        return [values[index] for index in range(len(keys))]

    async def mget_dict(self, keys: list[str]) -> dict[str, DATA_TYPES | None]:
        """Get multiple keys at once as a dict

        Handles all supported data types including sets.

        Args:
            keys (list[str]): Keys in the format 'ris:[data_type]:[key]' (see mget() for more info)

        Returns:
            dict[str, DATA_TYPES]: Key value pairs

        Raises:
            ValueError: Invalid key format
        """
        return dict(zip(keys, await self.mget(keys)))

    async def mget_dict_short(self, keys: list[str]) -> dict[str, DATA_TYPES | None]:
        """Get multiple keys at once as a dict without the 'ris:[data_type]:' prefix

        Handles all supported data types including sets.

        Args:
            keys (list[str]): Keys in the format 'ris:[data_type]:[key]' (see mget() for more info)

        Returns:
            dict[str, DATA_TYPES]: Key value pairs

        Raises:
            ValueError: Invalid key format
        """
        return {key.split(":", 2)[2]: value for key, value in (await self.mget_dict(keys)).items()}

    async def keys(self, pattern: str) -> list[str]:
        """Find keys

        Args:
            pattern (str): Pattern

        Returns:
            list[str]: Keys
        """
        if not self._check_key_format(pattern):
            pattern = f"ris:[sx][sifbj]:{pattern}"

        return await self.redis_client.keys(pattern)  # type: ignore[no-any-return]

    def _check_key_format(self, key: str) -> tuple[str, str] | None:
        """Check key format

        Schema:
            ris:[data_type]:[key]
            data_type: .. see TYPE_MAP
            key: str

        Args:
            key (str): Key

        Returns:
            tuple[str, str] | None: Tuple of data_type and key or None if key is not in the correct format

        Raises:
            ValueError: If key contains "ris:" prefix but is not in the correct format
        """
        if key.startswith("ris:"):
            if match := re.match(r"ris:([sx][sifbj]):(.+)", key):
                return tuple(match.groups())  # type: ignore[return-value]
            raise ValueError("Invalid key format, correct format is 'ris:[data_type]:[key]'")
        return None
