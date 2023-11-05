import os
from asyncio import as_completed
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Awaitable, Callable

from ris import common
from ris.data_provider import ProviderResult, danbooru, gelbooru

SAUCENAO_API_KEY = os.environ["SAUCENAO_API_KEY"]
SAUCENAO_MIN_SIMILARITY = float(os.environ["SAUCENAO_MIN_SIMILARITY"])


@dataclass
class Result:
    search_provider: str
    provider_result: ProviderResult


async def find_existing_results(image_id: str) -> list[ProviderResult]:
    return await common.redis_storage.get_provider_results_by_image(image_id)


async def saucenao_search(image_url: str, image_id: str) -> AsyncGenerator[Result, None]:
    url = f"https://saucenao.com/search.php?url={image_url}"

    params: dict[str, Any] = {"output_type": 2}
    if SAUCENAO_API_KEY:
        params["api_key"] = SAUCENAO_API_KEY

    async with common.http_session.get(url, headers={"User-Agent": common.USER_AGENT}, params=params) as response:
        data = await response.json()

    known_providers: dict[int, Callable[[int], Awaitable[ProviderResult]]] = {
        9: danbooru,
        12: gelbooru,
    }

    id_map = {
        9: "danbooru_id",
        12: "gelbooru_id",
    }

    filtered_data = [
        item
        for item in data.get("results", [])
        if float(item["header"]["similarity"]) >= SAUCENAO_MIN_SIMILARITY
        and item["header"]["index_id"] in known_providers
    ]

    tasks: list[Awaitable[ProviderResult]] = []
    for item in filtered_data:
        provider = known_providers[item["header"]["index_id"]]
        id_field = id_map[item["header"]["index_id"]]
        tasks.append(provider(item["data"][id_field]))

    for task in as_completed(tasks):
        result = await task
        if result:
            await common.redis_storage.add_provider_result(image_id, result)
            yield Result(search_provider="saucenao", provider_result=result)
