import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import uvloop
from redis.asyncio import Redis
from redis.asyncio.client import Pipeline

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


@pytest.fixture
async def mock_redis_client() -> AsyncMock:
    mock_client = MagicMock(spec=Redis)
    mock_client.set = AsyncMock()
    mock_client.get = AsyncMock()
    mock_client.get.return_value = None
    mock_client.smembers = AsyncMock()
    mock_client.smembers.return_value = set()
    mock_client.sadd = AsyncMock()
    mock_client.srem = AsyncMock()
    mock_client.keys = AsyncMock()
    mock_client.keys.return_value = []
    mock_client.delete = AsyncMock()
    mock_client.mget = AsyncMock()
    mock_client.mget.return_value = []

    pipeline = MagicMock(spec=Pipeline)
    pipeline.execute = AsyncMock()
    pipeline.execute.return_value = []

    mock_client.pipeline = MagicMock()
    mock_client.pipeline.return_value = pipeline
    return mock_client
