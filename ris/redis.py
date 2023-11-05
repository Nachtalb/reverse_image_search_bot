import asyncio
import logging
import re
from typing import TypedDict

from redis.asyncio import Redis

from ris.data_provider import ProviderResult


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
