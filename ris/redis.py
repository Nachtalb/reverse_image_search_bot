import logging
from typing import Any

from redis.asyncio import Redis

from ris.data_provider import ProviderResult


class RedisStorage:
    def __init__(self, redis_client: Redis):
        """Redis storage

        Args:
            redis_client (Redis): Redis client
        """
        self.redis_client = redis_client
        self.logger = logging.getLogger("ris:redis")

    async def add_provider_result(self, image_id: str, result: ProviderResult) -> None:
        """Add provider result to storage and link it to image_id

        Args:
            image_id (str): Image id
            result (ProviderResult): Provider result
        """
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
        data = await self.redis_client.get("ris:provider_result:" + search_key)
        return ProviderResult.from_json(data) if data else None

    async def get_provider_results(self, search_keys: list[str]) -> list[ProviderResult]:
        """Get provider results by search keys

        Args:
            search_keys (list[str]): Search keys

        Returns:
            list[ProviderResult]: Provider results
        """
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
        return await self.redis_client.smembers("ris:image_to_provider_result_link:" + image_id)  # type: ignore[no-any-return, misc]

    async def get_provider_results_by_image(self, image_id: str) -> list[ProviderResult]:
        """Get provider results by image id

        Args:
            image_id (str): Image id

        Returns:
            list[ProviderResult]: Provider results
        """
        return await self.get_provider_results(await self.get_provider_results_ids_by_image(image_id))

    async def add_no_found_entry(self, image_id: str) -> None:
        """Add no found entry

        Args:
            image_id (str): Image id
        """
        await self.redis_client.set(f"ris:no_found:{image_id}", "1", ex=60 * 60 * 24)

    async def check_no_found_entry(self, image_id: str) -> bool:
        """Check no found entry

        Args:
            image_id (str): Image id

        Returns:
            bool: Does no found entry exists
        """
        return await self.redis_client.exists(f"ris:no_found:{image_id}")  # type: ignore[no-any-return]

    async def reset_all_no_founds(self) -> None:
        """Reset all no found entries"""
        await self.redis_client.delete(*await self.redis_client.keys("ris:no_found:*"))

    async def set_user_setting(self, user_id: int, setting_id: str, value: Any) -> None:
        """Set user setting

        Args:
            user_id (str): User id
            setting_id (str): Setting id
            value (Any): Setting value
        """
        self.logger.debug("Setting user setting %s %s %s", user_id, setting_id, value)
        await self.redis_client.set(f"ris:settings:{user_id}:{setting_id}", value)

    async def get_user_setting(self, user_id: int, setting_id: str) -> Any:
        """Get user setting

        Args:
            user_id (str): User id
            setting_id (str): Setting id

        Returns:
            Any: Setting value
        """
        self.logger.debug("Getting user setting %s %s", user_id, setting_id)
        return await self.redis_client.get(f"ris:settings:{user_id}:{setting_id}")

    async def set_user_setting_set(self, user_id: int, setting_id: str, value: set[str]) -> None:
        """Set user setting set

        Args:
            user_id (str): User id
            setting_id (str): Setting id
            value (set[str]): Setting value
        """
        self.logger.debug("Setting user setting set %s %s %s", user_id, setting_id, value)
        current_members = await self.get_user_setting_set(user_id, setting_id)
        if to_remove := current_members - set(value):
            await self.redis_client.srem(f"ris:settings:{user_id}:{setting_id}", *to_remove)  # type: ignore[misc]

        if to_add := set(value) - current_members:
            await self.redis_client.sadd(f"ris:settings:{user_id}:{setting_id}", *to_add)  # type: ignore[misc]

    async def get_user_setting_set(self, user_id: int, setting_id: str) -> set[str]:
        """Get user setting set

        Args:
            user_id (str): User id
            setting_id (str): Setting id

        Returns:
            set[str]: Setting value
        """
        self.logger.debug("Getting user setting set %s %s", user_id, setting_id)
        return await self.redis_client.smembers(f"ris:settings:{user_id}:{setting_id}")  # type: ignore[no-any-return, misc]

    async def get_all_user_settings(self, user_id: int) -> dict[str, str | set[str]]:
        """Get all user settings

        Get all settings by ris:settings:{user_id}:*

        Args:
            user_id (int): User id

        Returns:
            dict[str, str]: User settings
        """
        self.logger.debug("Getting all user settings %s", user_id)
        keys = await self.redis_client.keys(f"ris:settings:{user_id}:*")
        settings = {}

        for key in keys:
            key_type = await self.redis_client.type(key)
            value: str | set[str]
            if key_type == "string":
                value = await self.redis_client.get(key)
            elif key_type == "set":
                value = await self.redis_client.smembers(key)  # type: ignore[misc]
            else:
                self.logger.warning("Unknown key type: %s", key_type)
                continue
            setting_name = key.split(":")[-1]
            settings[setting_name] = value

        return settings
