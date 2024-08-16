import asyncio
import json
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
    if return_cached and await SEARCH_CACHE.exists(file.name, sub_dir=engine_name):
        return await SEARCH_CACHE.get_json(file.name, sub_dir=engine_name)

    result: list[Normalized] | Errored
    try:
        result = normalizer(await engine(str(file), session), file.name)
    except (aiohttp.ClientResponseError, aiohttp.ClientError) as error:
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
        if "error" in result:
            continue
        distributor.distribute(result, pre_process=check_similarity)

    await distributor.join()


async def amain(session: aiohttp.ClientSession) -> None:
    parser = ArgumentParser()
    parser.add_argument("file", type=str, help="File or URL to download")
    parser.add_argument("-F", "--no-file-cache", action="store_true", help="Disable download cache (download again)")
    parser.add_argument("-R", "--no-search-cache", action="store_true", help="Disable search cache (search again)")
    parser.add_argument("-P", "--no-provider-cache", action="store_true", help="Disable provider cache (fetch again)")
    args = parser.parse_args()

    if os.path.exists(args.file):
        file = await save_file(AsyncPath(args.file), use_cache=not args.no_file_cache)
    else:
        file = await download_file(url=args.file, dir=DOWNLOAD_DIR, session=session, use_cache=not args.no_file_cache)

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
