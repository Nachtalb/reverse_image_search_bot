import logging
from asyncio import Queue, create_task, gather
from typing import TYPE_CHECKING, Any, AsyncGenerator, Awaitable

from ris import common
from ris.provider import fetch_provider_data
from ris.provider_engines import ProviderData
from ris.search_engines import SearchResult, iqdb, saucenao

if TYPE_CHECKING:
    from ris.redis_models import UserSettings

logger = logging.getLogger("ris.search")


SEARCH_ENGINES = {
    "IQDB": iqdb,
    "SauceNAO": saucenao,
}


PRIORITIZED_PROVIDERS = {
    "danbooru": 0,
    "zerochan": 0,
    "pixiv": 20,
    "3dbooru ": 20,
    "twitter": 20,
    "yandere": 30,
    "gelbooru": 30,
    "konachan": 30,
    "eshuushuu": 30,
}


def filter_by_priority(results: list[ProviderData]) -> list[ProviderData]:
    """Filters out by priority.

    - Providers are initially filtered to only include those with the highest priority number (e.g., all with priority `0` if any, otherwise all with the next lowest number like `20`).
    - Within this filtered set, if multiple providers have the same `priority_key`, only the provider with the greatest number of `extra_links` is kept.
    - Each `priority_key` is represented at most once in the final list, corresponding to the provider with the most `extra_links` among those with the same priority level.
    - If a provider's `priority_key` is not in the `PRIORITIZED_PROVIDERS` dictionary, it is assigned the lowest priority by default.

    Args:
        results (list[ProviderData]): The results to filter.

    Returns:
        list[ProviderData]: The filtered results.
    """
    if not results:
        return results
    default_priority = max(PRIORITIZED_PROVIDERS.values()) + 10
    highest_priority = min([PRIORITIZED_PROVIDERS.get(provider.priority_key, default_priority) for provider in results])
    top_priority_providers = [
        provider
        for provider in results
        if PRIORITIZED_PROVIDERS.get(provider.priority_key, default_priority) == highest_priority
    ]
    sorted_providers = sorted(top_priority_providers, key=lambda x: (-len(x.extra_links), x.priority_key))
    unique_providers = []
    seen_keys = set()
    for provider in sorted_providers:
        if provider.priority_key not in seen_keys:
            unique_providers.append(provider)
            seen_keys.add(provider.priority_key)

    return unique_providers


async def search(image_url: str, image_id: str, user_settings: "UserSettings") -> AsyncGenerator[ProviderData, None]:
    """Step 1: Searches for the image on enabled search engines and yields the results.

    1. Checks if the image is marked as not found in the cache.
    2. Checks if the image is cached.
    3. Starts the search engine producer and consumer. (Step 2)
    4. Yields the results from the consumer.

    Args:
        image_url (str): URL to the image to search for.
        image_id (str): Unique ID for the image.
        user_settings (UserSettings): The user's settings.

    Yields:
        ProviderData: The results from the search engines.
    """
    log_prefix = f"[{image_id}].search:"
    logger.info(f"{log_prefix} starting search")
    logger.debug(f"{log_prefix} {user_settings=}")

    if user_settings.cache_enabled:
        logger.debug(f"{log_prefix} checking cache")
        try:
            if await common.redis_storage.is_image_marked_as_not_found(image_id):
                logger.debug(f"{log_prefix} image is marked as not found")
                return
            if results := await common.redis_storage.get_cached_provider_data_by_image(image_id):
                logger.debug(f"{log_prefix} image is cached")

                if user_settings.best_results_only:
                    before = len(results)
                    results = filter_by_priority(results)
                    logger.debug(f"{log_prefix} {before=} after={len(results)}")
                for result in results:
                    yield result
                return
            logger.debug(f"{log_prefix} image is not cached")
        except Exception as e:
            logger.exception(e)
            raise

    logger.debug(f"{log_prefix} starting search engine producer and consumer")
    search_queue: Queue[SearchResult | None] = Queue()
    provider_queue: Queue[ProviderData | None] = Queue()

    search_producer = create_task(
        _search_engine_producer(image_url, image_id, search_queue, user_settings.enabled_engines)
    )
    search_consumer = create_task(
        _search_engine_consumer(search_queue, provider_queue, user_settings.cache_enabled, image_id)
    )

    logger.debug(f"{log_prefix} starting provider consumers")
    found = False
    deferred: list[ProviderData] = []
    while True:
        provider_data = await provider_queue.get()
        if provider_data is None:
            logger.debug(f"{log_prefix} received stop signal from provider consumer")
            break
        logger.debug(f"{log_prefix} {provider_data.provider_id=} received provider data")
        if user_settings.cache_enabled:
            logger.debug(f"{log_prefix} {provider_data.provider_id=} caching provider data")
            await common.redis_storage.cache_provider_data(image_id, provider_data)
        found = True

        if user_settings.best_results_only:
            deferred.append(provider_data)
            logger.debug(f"{log_prefix} {provider_data.provider_id=} deferring result for best results only")
            continue
        logger.debug(f"{log_prefix} {provider_data.provider_id=} yielding result")
        yield provider_data

    if user_settings.best_results_only and deferred:
        before = len(deferred)
        logger.debug(f"{log_prefix} filtering deferred results for best results only")
        for index, result in enumerate(filter_by_priority(deferred)):
            yield result
        logger.debug(f"{log_prefix} {before=} after={index + 1}")

    logger.debug(f"{log_prefix} stopping search engine producer and consumer")
    if not found and user_settings.cache_enabled:
        logger.debug(f"{log_prefix} marking image as not found")
        await common.redis_storage.mark_image_as_not_found(image_id)

    await search_producer
    await search_consumer


async def _search_engine_producer(
    image_url: str, image_id: str, queue: Queue[SearchResult | None], enabled_engines: set[str]
) -> None:
    """Step 2: Starts the search engine producers and relays the results to the consumer.

    1. Starts the search engine producers.
    2. Relays the results to the consumer. (Step 3)
    3. Signals the consumer to stop.

    Args:
        image_url (str): URL to the image to search for.
        image_id (str): Unique ID for the image.
        queue (Queue[SearchResult | None]): Queue to relay the results to.
        enabled_engines (set[str]): The enabled search engines.

    Returns:
        None: Returns when all producers have finished.
    """
    log_prefix = f"[{image_id}]._search_engine_producer:"
    logger.debug(f"{log_prefix} starting search engines")
    await gather(
        *[
            _relay_generator_to_queue(engine(image_url, image_id), queue)
            for name, engine in SEARCH_ENGINES.items()
            if name in enabled_engines
        ],
        return_exceptions=True,
    )
    logger.debug(f"{log_prefix} search engines finished, stopping ...")
    await queue.put(None)


async def _search_engine_consumer(
    queue: Queue[SearchResult | None], provider_queue: Queue[ProviderData | None], cache_enabled: bool, image_id: str
) -> None:
    """Step 3: Consumes the results from the search engine producers and starts the provider consumers.

    1. Consumes the results from the search engine producers.
    2. Checks if the provider has already been seen.
    3. Checks if the provider is cached.
    4. Starts the provider consumers. (Relays the results to the provider consumers (Step 1.4)
    5. Signals the provider consumers to stop.

    Args:
        queue (Queue[SearchResult | None]): Queue to consume the results from.
        provider_queue (Queue[ProviderData | None]): Queue to relay the results to.
        cache_enabled (bool): Whether or not caching is enabled.
        image_id (str): Unique ID for the image only used for logging.

    Returns:
        None: Returns when all providers have finished.
    """
    log_prefix = f"[{image_id}]._search_engine_consumer:"
    logger.debug(f"{log_prefix} starting")
    provider_ids_seen = set()
    provider_tasks = []

    while True:
        result = await queue.get()
        if result is None:  # None is used as the signal to stop
            logger.debug(f"{log_prefix} received stop signal from search engine producer")
            break

        if result.provider_id in provider_ids_seen:
            logger.debug(f"{log_prefix} {result.provider=} {result.provider_id=} already seen")
            continue

        provider_ids_seen.add(result.provider_id)

        if cache_enabled and (cached_data := await common.redis_storage.get_cached_provider_data(result.provider_id)):
            logger.debug(f"{log_prefix} {result.provider=} {result.provider_id=} cached")
            await provider_queue.put(cached_data[0])
            continue

        logger.debug(f"{log_prefix} {result.provider=} {result.provider_id=} starting provider...")
        provider_tasks.append(
            _relay_to_queue(
                fetch_provider_data(
                    search_engine=result.search_provider,
                    provider_name=result.provider,
                    provider_id=result.post_id,
                    extra_data=result.extra_data,
                ),
                provider_queue,
            )
        )

    logger.debug(f"{log_prefix} Waiting for providers to finish")
    await gather(*provider_tasks, return_exceptions=True)
    await provider_queue.put(None)


async def _relay_generator_to_queue(
    generator: AsyncGenerator[SearchResult, None], queue: Queue[SearchResult | None]
) -> None:
    """Relays the results of an async generator to a queue.

    Args:
        generator (AsyncGenerator[SearchResult, None]): The async generator to relay.
        queue (Queue[SearchResult | None]): The queue to relay the results to.
    """
    try:
        async for item in generator:
            await queue.put(item)
    except Exception as e:
        logger.exception(e)
        raise


async def _relay_to_queue(awaitable: Awaitable[Any], queue: Queue[Any]) -> None:
    """Relays the result of an awaitable to a queue.

    Args:
        awaitable (Awaitable[Any]): The awaitable to await.
        queue (Queue[Any]): The queue to relay the result to.
    """
    try:
        await queue.put(await awaitable)
    except Exception as e:
        logger.exception(e)
        raise
