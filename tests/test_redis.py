from unittest.mock import AsyncMock, MagicMock

import pytest

from ris.redis import RedisStorage


class RedisStorageImpl(RedisStorage):
    redis_client: MagicMock  # Set so that mypy doesn't complain


class TestRedisStorage:
    @pytest.fixture(autouse=True)
    async def setup_method(self, mock_redis_client: AsyncMock) -> None:
        """Setup method that's called before each test function."""
        self.redis = RedisStorageImpl(mock_redis_client)

    async def test_set_user_setting(self) -> None:
        user_id = 123456
        key = "theme"
        value = "dark"
        self.redis.set = AsyncMock()  # type: ignore[method-assign]
        await self.redis.set_user_setting(user_id, key, value)
        self.redis.set.assert_awaited_with(f"settings:{user_id}:{key}", value)

    async def test_get_user_setting_with_default(self) -> None:
        user_id = 123456
        key = "language"
        default = "en"
        self.redis.get = AsyncMock()  # type: ignore[method-assign]
        await self.redis.get_user_setting(user_id, key, default)
        self.redis.get.assert_awaited_with(f"settings:{user_id}:{key}", default)

    async def test_get_user_setting_without_default(self) -> None:
        user_id = 123456
        key = "notifications"
        self.redis.get = AsyncMock()  # type: ignore[method-assign]
        await self.redis.get_user_setting(user_id, key)
        self.redis.get.assert_awaited_with(f"settings:{user_id}:{key}", None)
