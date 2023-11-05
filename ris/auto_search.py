import asyncio
import logging
import os
import re
from asyncio import Queue, as_completed, gather
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Awaitable, Callable

from ris import common
from ris.data_provider import ProviderResult, danbooru, gelbooru, threedbooru, yandere, zerochan

SAUCENAO_API_KEY = os.environ["SAUCENAO_API_KEY"]
SAUCENAO_MIN_SIMILARITY = float(os.environ["SAUCENAO_MIN_SIMILARITY"])

logger = logging.getLogger("ris.search")


@dataclass
class Result:
    search_provider: str
    provider_result: ProviderResult
    similarity: float = -1.0


async def find_existing_results(image_id: str) -> list[ProviderResult]:
    """Find existing results in redis storage.

    Args:
        image_id (str): Image id.

    Returns:
        list[ProviderResult]: List of existing results.
    """
    logger.info("Searching for existing results for image %s", image_id)
    return await common.redis_storage.get_provider_results_by_image(image_id)


async def saucenao_search(image_url: str, image_id: str) -> AsyncGenerator[Result, None]:
    """Search for image using saucenao.

    Args:
        image_url (str): Image url.
        image_id (str): Image id.

    Yields:
        AsyncGenerator[Result, None]: Async generator of results.
    """
    logger.info("Searching for image %s using saucenao", image_id)
    url = f"https://saucenao.com/search.php?url={image_url}"

    params: dict[str, Any] = {"output_type": 2}
    if SAUCENAO_API_KEY:
        params["api_key"] = SAUCENAO_API_KEY

    async with common.http_session.get(url, headers={"User-Agent": common.USER_AGENT}, params=params) as response:
        data = await response.json()

    known_providers: list[int] = [
        9,  #  danbooru
        12,  #  yandere
        25,  #  gelbooru
    ]

    ids: dict[str, Callable[[int], Awaitable[ProviderResult | None]]] = {
        "danbooru_id": danbooru,
        "yandere_id": yandere,
        "gelbooru_id": gelbooru,
    }

    filtered_data = [
        item
        for item in data.get("results", [])
        if float(item["header"]["similarity"]) >= SAUCENAO_MIN_SIMILARITY
        and item["header"]["index_id"] in known_providers
    ]

    used_ids: set[str] = set()
    tasks: list[Awaitable[ProviderResult | None]] = []
    for item in filtered_data:
        for key, provider in ids.items():
            if key not in used_ids and key in item["data"]:
                used_ids.add(key)
                tasks.append(ids[key](item["data"][key]))

    for task in as_completed(tasks):
        result = await task
        if result:
            yield Result(
                search_provider="saucenao", provider_result=result, similarity=float(item["header"]["similarity"])
            )


async def iqdb(image_url: str, image_id: str) -> AsyncGenerator[Result, None]:
    """Search for image using iqdb.

    Specifically only search e-shuushuu (6), zerochan (11) and 3dbooru (7). The remaining providers
    are covered by saucenao which provides better results.

    Args:
        image_url (str): Image url.
        image_id (str): Image id.

    Yields:
        AsyncGenerator[Result, None]: Async generator of results.
    """
    logger.info("Searching for image %s using iqdb", image_id)
    url = f"https://iqdb.org/?url={image_url}&service[]=6&service[]=11&service[]=7"

    async with common.http_session.get(url, headers={"User-Agent": common.LEGIT_USER_AGENT}) as response:
        html = await response.text()

    matches = re.findall(
        r'<div><table><tr><th>Best match</th></tr><tr><td class=\'image\'><a href="([^"]+)"><img src=\'([^"]+)\''
        r' alt="[^"]*" title="[^"]*" width=\'\d+\' height=\'\d+\'></a></td>.*?<td><img alt="icon"'
        r' src="/icon/[^.]+\.ico" class="service-icon">([^<]+)</td>.*?<td>(\d+×\d+) \[([^\]]+)\]</td>.*?<td>(\d+)%'
        r" similarity</td>",
        html,
        re.DOTALL,
    )

    provider_map = {
        "Zerochan": zerochan,
        "3dbooru": threedbooru,
    }

    for match in matches:
        provider = match[2].strip()
        post_link = match[0].strip()
        post_id = int(post_link.split("/")[-1])
        thumbnail_src = match[1].strip()
        size = match[3].strip()
        nsfw = match[4].strip().lower() != "safe"
        similarity = match[5].strip()

        if provider in provider_map:
            result = await provider_map[provider](post_id)
            if result:
                yield Result(search_provider="iqdb", provider_result=result, similarity=float(similarity))
        else:
            result = ProviderResult(
                provider_id=f"iqdb:{provider.lower()}-{post_id}",
                provider_link=post_link,
                main_file=thumbnail_src,
                fields={
                    "size": size,
                    "nsfw": nsfw,
                },
            )
            yield Result(search_provider="iqdb", provider_result=result, similarity=float(similarity))


SEARCH_ENGINES = {
    "IQDB": iqdb,
    "SauceNAO": saucenao_search,
}


async def consume(generator: AsyncGenerator[Result, None], queue: Queue[Result | None]) -> None:
    """Consume async generator and put results into queue.

    Args:
        generator (AsyncGenerator[Result, None]): Async generator of results.
        queue (Queue[Result | None]): Queue to put results into.
    """
    async for item in generator:
        await queue.put(item)


async def producer(image_url: str, image_id: str, queue: Queue[Result | None], enabled_engines: set[str]) -> None:
    """Produce results from search engines.

    Args:
        image_url (str): Image url.
        image_id (str): Image id.
        queue (Queue[Result | None]): Queue to put results into.
        enabled_engines (set[str]): List of enabled search engines.
    """
    await gather(
        *[
            consume(engine(image_url, image_id), queue)
            for name, engine in SEARCH_ENGINES.items()
            if name in enabled_engines
        ],
        return_exceptions=True,
    )
    await queue.put(None)


async def consumer(queue: Queue[Result | None]) -> AsyncGenerator[Result, None]:
    """Consume results from queue.

    Args:
        queue (Queue[Result | None]): Queue to consume results from.

    Yields:
        AsyncGenerator[Result, None]: Async generator of results.
    """
    while True:
        result = await queue.get()
        if result is None:  # None is used as the signal to stop
            break
        yield result


async def search_all_engines(
    image_url: str, image_id: str, enabled_engines: set[str] = set(SEARCH_ENGINES.keys())
) -> AsyncGenerator[Result, None]:
    """Search for image using all search engines.

    It also stores the results in redis storage.

    Args:
        image_url (str): Image url.
        image_id (str): Image id.
        enabled_engines (set[str], optional): List of enabled search engines. Defaults to all available.

    Yields:
        AsyncGenerator[Result, None]: Async generator of results.
    """
    queue: Queue[Result | None] = Queue()
    producer_task = asyncio.create_task(producer(image_url, image_id, queue, enabled_engines))

    async for item in consumer(queue):
        yield item
        await common.redis_storage.add_provider_result(image_id, item.provider_result)

    await producer_task
