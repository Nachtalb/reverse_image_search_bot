import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import uvloop
from redis.asyncio import Redis

from ris.provider_engines import ProviderData

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


@pytest.fixture
async def mock_redis_client() -> AsyncMock:
    mock_client = MagicMock(spec=Redis)
    mock_client.set = AsyncMock()
    mock_client.get = AsyncMock()
    mock_client.get.return_value = None
    mock_client.smembers = AsyncMock()
    mock_client.smembers.return_value = set()
    mock_client.sismember = AsyncMock()
    mock_client.sadd = AsyncMock()
    mock_client.srem = AsyncMock()
    mock_client.keys = AsyncMock()
    mock_client.keys.return_value = []
    mock_client.delete = AsyncMock()
    mock_client.mget = AsyncMock()
    mock_client.mget.return_value = []
    mock_client.eval = AsyncMock()
    mock_client.exists = AsyncMock()
    return mock_client


@pytest.fixture
def provider_data() -> ProviderData:
    return ProviderData(
        provider_id="testbooru-123456",
        main_files=["https://testbooru.org/images/123456.jpg"],
        extra_links=["https://testbooru.org/images/123456.png"],
        fields={"nsfw": False, "source": "https://testbooru.org/post/123456", "tags": ["tag1", "tag2"]},
        provider_link="https://testbooru.org/post/123456",
    )


@pytest.fixture
async def provider_data_list() -> list[ProviderData]:
    return [
        ProviderData(
            provider_id="testbooru-123456",
            main_files=["https://testbooru.org/images/123456.jpg"],
            extra_links=["https://testbooru.org/images/123456.png"],
            fields={"nsfw": False, "source": "https://testbooru.org/post/123456", "tags": ["tag1", "tag2"]},
            provider_link="https://testbooru.org/post/123456",
        ),
        ProviderData(
            provider_id="testbooru-654321",
            main_files=["https://testbooru.org/images/654321.jpg"],
            extra_links=["https://testbooru.org/images/654321.png"],
            fields={"nsfw": False, "source": "https://testbooru.org/post/654321", "tags": ["tag3", "tag4"]},
            provider_link="https://testbooru.org/post/654321",
        ),
    ]
