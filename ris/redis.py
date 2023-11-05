from typing import Iterable

from redis.asyncio import Redis

from ris.data_provider import ProviderResult


class RedisStorage:
    def __init__(self, redis_client: Redis):
        self.redis_client = redis_client

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

    async def set_enabled_engines(self, user_id: int, enabled_engines: Iterable[str]) -> None:
        """Set enabled engines for user

        Args:
            user_id (int): User id
            enabled_engines (list[str]): Enabled engines
        """
        current_members = await self.get_enabled_engines(user_id)
        if to_remove := current_members - set(enabled_engines):
            await self.redis_client.srem(f"ris:settings:{user_id}:enabled_engines", *to_remove)  # type: ignore[misc]

        if to_add := set(enabled_engines) - current_members:
            await self.redis_client.sadd(f"ris:settings:{user_id}:enabled_engines", *to_add)  # type: ignore[misc]

    async def get_enabled_engines(self, user_id: int) -> set[str]:
        """Get enabled engines for user

        Args:
            user_id (int): User id

        Returns:
            list[str]: Enabled engines
        """
        return await self.redis_client.smembers(f"ris:settings:{user_id}:enabled_engines")  # type: ignore[no-any-return, misc]

    async def get_all_user_settings(self, user_id: int) -> dict[str, str]:
        """Get all user settings

        Get all settings by ris:settings:{user_id}:*

        Args:
            user_id (int): User id

        Returns:
            dict[str, str]: User settings
        """
        keys = await self.redis_client.keys(f"ris:settings:{user_id}:*")
        return {key.split(":")[-1]: await self.redis_client.get(key) for key in keys}
