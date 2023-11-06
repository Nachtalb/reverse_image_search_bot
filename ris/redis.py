import logging
from typing import TypedDict

from redis.asyncio import Redis

from ris.data_provider import ProviderResult
from ris.redis_data_types import DATA_TYPES, RedisStorageDataTypesMixin


class CacheInfo(TypedDict):
    entries_results: int
    entries_links: int
    entries_not_found: int
    entries: int
    volume_results: int
    volume_links: int
    volume_not_found: int
    volume: int


class RedisStorage(RedisStorageDataTypesMixin):
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

    async def set_user_setting(self, user_id: int, key: str, value: DATA_TYPES) -> None:
        """Set user setting

        Args:
            user_id (str): User ID
            key (str): Setting key
            value (DATA_TYPES): Setting value
        """
        self.logger.debug("Setting user setting %s %s %s", user_id, key, value)
        await self.set(f"settings:{user_id}:{key}", value)

    async def get_user_setting(self, user_id: int, key: str, default: DATA_TYPES | None = None) -> DATA_TYPES:
        """Get user setting

        Args:
            user_id (str): User ID
            key (str): Setting key
            default (DATA_TYPES | None, optional): If setting doesn't exist
                either return this value or raise KeyError if None. Defaults
                to None.

        Returns:
            DATA_TYPES: Setting value

        Raises:
            KeyError: If setting doesn't exist and default is None
        """
        self.logger.debug("Getting user setting %s %s", user_id, key)
        return await self.get(f"settings:{user_id}:{key}", default)

    async def get_user_settings(self, user_id: int) -> dict[str, DATA_TYPES]:
        """Get all settings for a user

        Args:
            user_id (int): User ID

        Returns:
            dict[str, DATA_TYPES]: User settings
        """
        self.logger.debug("Getting all user settings %s", user_id)
        keys = await self.keys(f"settings:{user_id}:*")
        return await self.mget_dict_short(keys)
