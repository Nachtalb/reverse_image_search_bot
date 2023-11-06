import asyncio
import json
import logging
import re
from typing import Callable, Type, TypedDict

from redis.asyncio import Redis

from ris.data_provider import ProviderResult

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


class CacheInfo(TypedDict):
    entries_results: int
    entries_links: int
    entries_not_found: int
    entries: int
    volume_results: int
    volume_links: int
    volume_not_found: int
    volume: int


class RedisStorage:
    def __init__(self, redis_client: Redis):
        """Redis storage

        Args:
            redis_client (Redis): Redis client
        """
        self.redis_client = redis_client
        self.logger = logging.getLogger("ris:redis")
        self.logger.setLevel(logging.DEBUG)

    async def add_provider_result(self, image_id: str, result: ProviderResult) -> None:
        """Add provider result to storage and link it to image_id

        Args:
            image_id (str): Image id
            result (ProviderResult): Provider result
        """
        self.logger.debug("Adding provider result %s", result)
        serialized_result = result.to_json()
        primary_key = result.provider_id
        await self.redis_client.set("ris:provider_result:" + primary_key, serialized_result)
        await self.redis_client.sadd("ris:image_to_provider_result_link:" + image_id, result.provider_id)  # type: ignore[misc]

    async def get_provider_result(self, search_key: str) -> ProviderResult | None:
        """Get provider result by search key

        Args:
            search_key (str): Search key

        Returns:
            ProviderResult | None: Provider result
        """
        self.logger.debug("Getting provider result %s", search_key)
        data = await self.redis_client.get("ris:provider_result:" + search_key)
        return ProviderResult.from_json(data) if data else None

    async def get_provider_results(self, search_keys: list[str]) -> list[ProviderResult]:
        """Get provider results by search keys

        Args:
            search_keys (list[str]): Search keys

        Returns:
            list[ProviderResult]: Provider results
        """
        self.logger.debug("Getting provider results %s", search_keys)
        keys = [f"ris:provider_result:{key}" for key in search_keys]
        results = await self.redis_client.mget(keys)
        return [ProviderResult.from_json(result) for result in results if result]

    async def get_provider_results_ids_by_image(self, image_id: str) -> list[str]:
        """Get provider results ids by image id

        Args:
            image_id (str): Image id

        Returns:
            list[str]: Provider results ids
        """
        self.logger.debug("Getting provider results ids by image id %s", image_id)
        return await self.redis_client.smembers("ris:image_to_provider_result_link:" + image_id)  # type: ignore[no-any-return, misc]

    async def get_provider_results_by_image(self, image_id: str) -> list[ProviderResult]:
        """Get provider results by image id

        Args:
            image_id (str): Image id

        Returns:
            list[ProviderResult]: Provider results
        """
        self.logger.debug("Getting provider results by image id %s", image_id)
        return await self.get_provider_results(await self.get_provider_results_ids_by_image(image_id))

    async def save_broadcast_message(self, from_chat_id: int, message_id: int) -> None:
        """Save broadcast message

        Args:
            message_id (int): Message id
        """
        self.logger.debug("Saving broadcast message %s %s", from_chat_id, message_id)
        await self.redis_client.set("ris:broadcast_message", f"{from_chat_id}:{message_id}")

    async def get_broadcast_message(self) -> tuple[int, int] | tuple[None, None]:
        """Get broadcast message

        Returns:
            tuple[int, int] | tuple[None, None]: Tuple of from_chat_id and message_id
        """
        self.logger.debug("Getting broadcast message")
        if await self.redis_client.exists("ris:broadcast_message"):
            return tuple(int(x) for x in (await self.redis_client.get("ris:broadcast_message")).split(":"))  # type: ignore[return-value]
        return None, None

    async def get_users(self) -> list[int]:
        """Get users

        Returns:
            list[int]: Users
        """
        self.logger.debug("Getting users")
        keys = await self.redis_client.keys("ris:search:user:*")
        return [int(key.split(":")[-1]) for key in keys]

    async def get_users_count(self) -> int:
        """Get users count

        Returns:
            int: Users count
        """
        self.logger.debug("Getting users count")
        return len(await self.redis_client.keys("ris:search:user:*"))

    async def incr_user_search_count(self, user_id: int) -> int:
        """Increment user search count

        Args:
            user_id (int): User id

        Returns:
            int: New search count
        """
        self.logger.debug("Incrementing user search count %s", user_id)
        await self.redis_client.incr("ris:search:total")
        return await self.redis_client.incr(f"ris:search:user:{user_id}")  # type: ignore[no-any-return]

    async def get_user_search_count(self, user_id: int) -> int:
        """Get user search count

        Args:
            user_id (int): User id

        Returns:
            int: Search count
        """
        self.logger.debug("Getting user search count %s", user_id)
        return int(await self.redis_client.get(f"ris:search:user:{user_id}"))

    async def get_total_search_count(self) -> int:
        """Get total search count

        Returns:
            int: Total search count
        """
        self.logger.debug("Getting total search count")
        return int(await self.redis_client.get("ris:search:total"))

    async def add_no_found_entry(self, image_id: str) -> None:
        """Add no found entry

        Args:
            image_id (str): Image id
        """
        self.logger.debug("Adding no found entry %s", image_id)
        await self.redis_client.set(f"ris:no_found:{image_id}", "1", ex=60 * 60 * 24)

    async def check_no_found_entry(self, image_id: str) -> bool:
        """Check no found entry

        Args:
            image_id (str): Image id

        Returns:
            bool: Does no found entry exists
        """
        self.logger.debug("Checking no found entry %s", image_id)
        return await self.redis_client.exists(f"ris:no_found:{image_id}")  # type: ignore[no-any-return]

    async def clear_not_found(self) -> int:
        """Clear not found entries

        Returns:
            int: Number of cleared entries
        """
        self.logger.debug("Clearing not found entries")
        keys = await self.redis_client.keys("ris:no_found:*")
        if keys:
            await self.redis_client.delete(*keys)
        return len(keys)

    async def clear_provider_results(self) -> int:
        """Clear results

        Returns:
            int: Number of cleared entries
        """
        self.logger.debug("Clearing results")
        total = 0
        if keys := await self.redis_client.keys("ris:provider_result:*"):
            await self.redis_client.delete(*keys)
            total = len(keys)
        if keys := await self.redis_client.keys("ris:image_to_provider_result_link:*"):
            await self.redis_client.delete(*keys)
        return total

    async def get_cache_info(self) -> CacheInfo:
        """Get cache info

        The cache info contains the number of entries and the volume of the entries:
        Returns:
            dict[str, int]: Cache info
        """
        keys_results = await self.redis_client.keys("ris:provider_result:*")
        keys_links = await self.redis_client.keys("ris:image_to_provider_result_link:*")
        keys_not_found = await self.redis_client.keys("ris:no_found:*")

        entries_results = len(keys_results)
        entries_links = len(keys_links)
        entries_not_found = len(keys_not_found)

        volume_results = 0
        volume_links = 0
        volume_not_found = 0

        for key in keys_results:
            volume_results += await self.redis_client.memory_usage(key)

        for key in keys_links:
            volume_links += await self.redis_client.memory_usage(key)

        for key in keys_not_found:
            volume_not_found += await self.redis_client.memory_usage(key)

        return {
            "entries_results": entries_results,
            "entries_links": entries_links,
            "entries_not_found": entries_not_found,
            "entries": entries_results + entries_links + entries_not_found,
            "volume_results": volume_results,
            "volume_links": volume_links,
            "volume_not_found": volume_not_found,
            "volume": volume_results + volume_links + volume_not_found,
        }

    async def clear_results_full(self) -> tuple[int, int]:
        """Clear results and not found entries

        Returns:
            tuple[int, int]: Number of cleared not found entries, Number of cleared results
        """
        self.logger.debug("Clearing results and not found entries")
        total_not_found = await self.clear_not_found()
        total_results = await self.clear_provider_results()
        return total_not_found, total_results

    async def set_user_setting(self, user_id: int, setting_id: str, value: str | int | float | bool | set[str]) -> None:
        """Set user setting

        Args:
            user_id (str): User id
            setting_id (str): Setting ID. Will be prefixed with "s_", "i_", "f_", "b_" or "x_" for str, int, float, bool or set respectively
            value (str | int | float | bool): Setting value
        """
        match value:
            case bool():
                if not setting_id.startswith("b_"):
                    setting_id = "b_" + setting_id
                value = int(value)
            case int():
                if not setting_id.startswith("i_"):
                    setting_id = "i_" + setting_id
            case float():
                if not setting_id.startswith("f_"):
                    setting_id = "f_" + setting_id
            case set():
                if not setting_id.startswith("x_"):
                    setting_id = "x_" + setting_id
            case _:
                if not setting_id.startswith("s_"):
                    setting_id = "s_" + setting_id

        self.logger.debug("Setting user setting %s %s %s", user_id, setting_id, value)

        if setting_id.startswith("x_") and isinstance(value, set):
            current_members = await self.redis_client.smembers(f"ris:settings:{user_id}:{setting_id}")  # type: ignore[misc]
            if to_remove := current_members - set(value):
                await self.redis_client.srem(f"ris:settings:{user_id}:{setting_id}", *to_remove)  # type: ignore[misc]

            if to_add := set(value) - current_members:
                await self.redis_client.sadd(f"ris:settings:{user_id}:{setting_id}", *to_add)  # type: ignore[misc]
        else:
            value = str(value)
            await self.redis_client.set(f"ris:settings:{user_id}:{setting_id}", value)

    async def get_user_setting(
        self, user_id: int, setting_id: str, default: str | int | float | bool | set[str] | None = None
    ) -> str | int | float | bool | set[str]:
        """Get user setting

        Args:
            user_id (str): User id
            setting_id (str): Setting ID.
            default (str | int | float | bool | set[str] | None, optional): Default value. None == raise KeyError. Defaults to None.

        Returns:
            str | int | float | bool | set[str]: Setting value

        Raises:
            KeyError: Setting not found and no default value
        """
        if not re.search(r"^[sifbx]_", setting_id):
            keys = await self.redis_client.keys(f"ris:settings:{user_id}:[sifbx]_{setting_id}")
            if keys:
                setting_id = keys[0].split(":")[-1]
            else:
                if default is not None:
                    return default
                raise KeyError(f"Setting {setting_id} not found")

        self.logger.debug("Getting user setting %s %s", user_id, setting_id)
        if setting_id.startswith("x_"):
            return await self.redis_client.smembers(f"ris:settings:{user_id}:{setting_id}")  # type: ignore[no-any-return, misc]

        value = await self.redis_client.get(f"ris:settings:{user_id}:{setting_id}")
        if setting_id.startswith("i_"):
            return int(value)
        elif setting_id.startswith("f_"):
            return float(value)
        elif setting_id.startswith("b_"):
            return bool(int(value))
        return value  # type: ignore[no-any-return]

    async def get_all_user_settings(self, user_id: int) -> dict[str, str | int | float | bool | set[str]]:
        """Get all user settings

        Get all settings by ris:settings:{user_id}:*

        Args:
            user_id (int): User id

        Returns:
            dict[str, str | int | float | bool | set[str]]: User settings
        """
        self.logger.debug("Getting all user settings %s", user_id)
        keys = await self.redis_client.keys(f"ris:settings:{user_id}:*")

        async def get_setting(key: str) -> tuple[str, str | int | float | bool | set[str]]:
            settings_id = key.split(":")[-1]
            return settings_id[2:], await self.get_user_setting(user_id, settings_id)

        return dict(await asyncio.gather(*[get_setting(key) for key in keys]))

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
