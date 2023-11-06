import json
import re
from typing import Callable, Type

from redis.asyncio import Redis

DATA_TYPES_CHECK = (str, int, float, bool, dict, list, set)
DATA_TYPES = str | int | float | bool | dict | list | set[str] | set[int] | set[float] | set[bool]
TYPE_MAP = {
    str: "s",
    int: "i",
    float: "f",
    bool: "b",
    dict: "j",  # As JSON
    list: "j",  # As JSON
    set[str]: "xs",
    set[int]: "xi",
    set[float]: "xf",
    set[bool]: "xb",
}

SERIALIZE_MAP: dict[Type[DATA_TYPES], Callable[[DATA_TYPES], str | set[str]]] = {
    int: str,
    float: str,
    bool: lambda x: str(int(x)),  # type: ignore[arg-type]
    set[str]: lambda x: {str(y) for y in x},  # type: ignore[union-attr]
    set[int]: lambda x: {str(y) for y in x},  # type: ignore[union-attr]
    set[float]: lambda x: {str(y) for y in x},  # type: ignore[union-attr]
    set[bool]: lambda x: {str(int(y)) for y in x},  # type: ignore[union-attr]
    dict: json.dumps,
    list: json.dumps,
}

DESERIALIZE_MAP: dict[Type[DATA_TYPES], Callable[[str | set[str]], DATA_TYPES]] = {
    int: int,  # type: ignore[dict-item]
    float: float,  # type: ignore[dict-item]
    bool: lambda x: bool(int(x)),  # type: ignore[arg-type]
    dict: json.loads,  # type: ignore[dict-item]
    list: json.loads,  # type: ignore[dict-item]
    set[int]: lambda x: {int(y) for y in x},
    set[float]: lambda x: {float(y) for y in x},
    set[bool]: lambda x: {bool(int(y)) for y in x},
}

TYPE_MAP_REVERSE = {v: k for k, v in TYPE_MAP.items()}


class RedisStorageDataTypesMixin:
    redis_client: Redis

    def _serialize(self, value: DATA_TYPES, key: str) -> str | set[str]:
        """Serialize value

        Args:
            value (DATA_TYPES): Value
            key (str): Key

        Returns:
            str | set[str]: Serialized value
        """
        if not self._check_key_format(key):
            raise ValueError("Invalid key format, correct format is 'ris:[data_type]:[key]'")
        _, data_type, _ = key.split(":", 2)
        _type = TYPE_MAP_REVERSE[data_type]
        if _type in SERIALIZE_MAP:
            return SERIALIZE_MAP[_type](value)
        return str(value)

    def _deserialize(self, value: str | set[str], key: str) -> DATA_TYPES:
        """Deserialize value

        Args:
            value (str): Value
            key (str): Key

        Returns:
            DATA_TYPES: Deserialized value
        """
        if not self._check_key_format(key):
            raise ValueError("Invalid key format, correct format is 'ris:[data_type]:[key]'")
        _, data_type, _ = key.split(":", 2)

        _type: Type[DATA_TYPES] = TYPE_MAP_REVERSE[data_type]
        if _type in DESERIALIZE_MAP:
            return DESERIALIZE_MAP[_type](value)
        return value

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
                data_type = TYPE_MAP[set[set_type]]  # type: ignore[valid-type]
                key = f"ris:{data_type}:{key}"

            value = self._serialize(value, key)

            current_set = await self.redis_client.smembers(key)  # type: ignore[misc]
            if to_remove := current_set - value:
                await self.redis_client.srem(key, *to_remove)  # type: ignore[misc]

            if to_add := value - current_set:
                await self.redis_client.sadd(key, *to_add)  # type: ignore[misc]
            return

        if not self._check_key_format(key):
            data_type = TYPE_MAP[type(value)]
            key = f"ris:{data_type}:{key}"

        value = self._serialize(value, key)
        await self.redis_client.set(key, value)  # type: ignore[arg-type]

    async def get(self, key: str, default: DATA_TYPES | None = None) -> DATA_TYPES:
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

        Raises:
            KeyError: Key not found or invalid key format
        """
        if not self._check_key_format(key):
            keys = await self.keys(key)
            if not keys:
                if default is None:
                    raise KeyError("Key not found")
                return default
            key = keys[0]

        _, data_type, _ = key.split(":", 2)

        if data_type[0] == "x":
            value = await self.redis_client.smembers(key)  # type: ignore[misc]
            return self._deserialize(value, key)

        value = await self.redis_client.get(key)
        return self._deserialize(value, key)

    async def mget(self, keys: list[str]) -> list[DATA_TYPES]:
        """Get multiple keys while handling all supported data types including sets

        Note:
            In comparison to get() this method does not accommodate not fully qualified keys. This means that
            keys must be in the format 'ris:[data_type]:[key]'. The reason for this is that, we'd have to search
            redis for every non fully qualified key to find the correct key. This is an easily avoidable overhead
            if the keys are already known.

        Args:
            keys (list[str]): Keys in the format 'ris:[data_type]:[key]'

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

        values: dict[int, DATA_TYPES] = {}

        if set_keys:
            pipe = self.redis_client.pipeline()
            [pipe.smembers(key) for key in set_keys.values()]
            for (index, key), value in zip(set_keys.items(), await pipe.execute()):
                values[index] = self._deserialize(value, key)

        if string_keys:
            for (index, key), value in zip(
                string_keys.items(), await self.redis_client.mget(list(string_keys.values()))
            ):
                values[index] = self._deserialize(value, key)

        return [values[index] for index in range(len(keys))]

    async def mget_dict(self, keys: list[str]) -> dict[str, DATA_TYPES]:
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

    async def mget_dict_short(self, keys: list[str]) -> dict[str, DATA_TYPES]:
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
            pattern = f"ris:[sifbjx][sifb]?:{pattern}"

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
            if match := re.match(r"ris:([sifbjx][sifb]?):(.+)", key):
                return tuple(match.groups())  # type: ignore[return-value]
            raise ValueError("Invalid key format, correct format is 'ris:[data_type]:[key]'")
        return None
