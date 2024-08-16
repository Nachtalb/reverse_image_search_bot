import asyncio
import json
import logging
import os
from argparse import ArgumentParser
from typing import Any, Callable

import aiohttp
from aiopath import AsyncPath

from .cache import SEARCH_CACHE
from .defaults import DOWNLOAD_DIR
from .distributor import Distributor
from .file import save_file
from .http import download_file
from .search import ENGINES
from .text import format_source
from .types import EngineFunc, Errored, Normalized, Normalizer, Source

__all__ = ["main"]


def print_source(source: Source) -> None:
    text, sources, links = format_source(source)
    print(text)
    print()
    print("Sources:")
    for source_link in sources:
        if isinstance(source_link, tuple):
            print(f" - {source_link[0]} ({source_link[1]})")
        else:
            print(f" - {source_link}")

    print()
    print("Links:")
    for link in links:
        print(f" - {link}")


async def use_engine(
    engine_name: str,
    engine: EngineFunc,
    normalizer: Normalizer,
    file: AsyncPath,
    session: aiohttp.ClientSession,
    return_cached: bool = True,
) -> list[Normalized] | Errored:
    logging.info(f"Searching for {file.name} with {engine_name}")
    logging.debug(f"Return cached: {return_cached}")
    logging.debug(f"Engine: {engine}")
    logging.debug(f"Normalizer: {normalizer}")
    if return_cached and await SEARCH_CACHE.exists(file.name, sub_dir=engine_name):
        logging.info("Using cached search result")
        logging.debug(f"Cache file: {await SEARCH_CACHE.cache_path(file.name, sub_dir=engine_name)}")
        results = await SEARCH_CACHE.get_json(file.name, sub_dir=engine_name)
        if isinstance(results, dict) and "error" in results:
            logging.error(f"Cached search result is an error: {results['error_message']}")
        logging.debug(f"Results: {results}")
        return results

    result: list[Normalized] | Errored
    try:
        logging.info(f"Start searching with {engine_name}")
        raw_results = await engine(str(file), session)
        logging.info(f"Search result for {engine_name}: {len(raw_results)} results")
        logging.debug(f"Raw results: {raw_results}")
        logging.info("Normalizing results")
        result = normalizer(raw_results, file.name)
        logging.info(f"Normalized results: {len(result)}")
        logging.debug(f"Normalized results: {result}")
    except (aiohttp.ClientResponseError, aiohttp.ClientError) as error:
        logging.error(f"An error occurred while searching with {engine_name}")
        error_message = str(error)
        error_data: Any = None
        if isinstance(error, aiohttp.ClientResponseError):
            error_message = error.message
            if error.history:
                try:
                    error_data = await error.history[-1].json()
                except (aiohttp.ContentTypeError, json.JSONDecodeError):
                    error_data = await error.history[-1].text()

        result = {
            "error": "An error occurred while searching.",
            "error_message": error_message,
            "error_data": error_data,
            "error_type": str(type(error)),
            "file": str(file),
            "engine": engine_name,  # type: ignore[typeddict-item]
        }
        logging.error(f"Error: {result}")
    logging.debug(
        f"Saving search result to cache for {engine_name} at {await SEARCH_CACHE.cache_path(file.name, sub_dir=engine_name)}"
    )
    await SEARCH_CACHE.set_json(file.name, result, sub_dir=engine_name)
    return result


def check_similarity(normalized: Normalized) -> Normalized | None:
    if normalized["similarity"] < 80:
        return None
    return normalized


async def search(
    file: AsyncPath,
    session: aiohttp.ClientSession,
    *,
    use_search_cache: bool = True,
    use_provider_cache: bool = True,
) -> None:
    logging.info(f"Searching for {file.name}")
    logging.debug(f"Search cache enabled: {use_search_cache}")
    logging.debug(f"Provider cache enabled: {use_provider_cache}")
    distributor = Distributor(print_source, {}, session, use_source_cache=use_provider_cache)

    for runner in asyncio.as_completed(
        (
            use_engine(
                engine_name=name,
                engine=engine,
                normalizer=normalizer,
                file=file,
                session=session,
                return_cached=use_search_cache,
            )
            for name, (engine, normalizer) in ENGINES.items()
        ),
    ):
        result = await runner
        if isinstance(result, list):
            engine = result[0].get("engine", "unknown")
            total = len(result)
        else:
            engine = result.get("engine", "unknown")
            total = 0
        logging.info(f"Search result for {engine}: {total} results")
        logging.debug(f"Results: {result}")
        if "error" in result:
            logging.error(f"Error: {result['error_message']}")  # type: ignore[call-overload]
            logging.error(f"Error: {result}")
            continue
        logging.info("Distributing results")
        distributor.distribute(result, pre_process=check_similarity)

    logging.info("Waiting for distributor to finish")
    await distributor.join()


def setup_logging(verbose: int) -> None:
    logging_levels = [logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG]
    logging_level = logging_levels[min(verbose, len(logging_levels) - 1)]
    logging.basicConfig(level=logging_level, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.error("This is an error message")
    logging.warning("This is a warning message")
    logging.info("This is an info message")
    logging.debug("This is a debug message")


async def amain(session: aiohttp.ClientSession) -> None:
    parser = ArgumentParser()
    parser.add_argument("file", type=str, help="File or URL to download")
    parser.add_argument("-F", "--no-file-cache", action="store_true", help="Disable download cache (download again)")
    parser.add_argument("-S", "--no-search-cache", action="store_true", help="Disable search cache (search again)")
    parser.add_argument("-P", "--no-provider-cache", action="store_true", help="Disable provider cache (fetch again)")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity level (up to -vvv)")
    args = parser.parse_args()

    setup_logging(args.verbose)
    logging.info("Starting")

    if os.path.exists(args.file):
        logging.info("Using local file")
        file = await save_file(AsyncPath(args.file), use_cache=not args.no_file_cache)
    else:
        logging.info("Downloading file")
        file = await download_file(url=args.file, dir=DOWNLOAD_DIR, session=session, use_cache=not args.no_file_cache)

    logging.info(f"File: {file}")

    await search(
        file, session, use_search_cache=not args.no_search_cache, use_provider_cache=not args.no_provider_cache
    )


async def session_wrapper(func: Callable[[aiohttp.ClientSession], Any]) -> None:
    async with aiohttp.ClientSession() as session:
        await func(session)


def main() -> None:
    try:
        asyncio.run(session_wrapper(amain))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
