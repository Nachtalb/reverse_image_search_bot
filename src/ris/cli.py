import asyncio
import json
import os
import shutil
from argparse import ArgumentParser
from typing import Any, Callable

import aiohttp
import xxhash
from aiopath import AsyncPath

from .defaults import DOWNLOAD_DIR, SEARCH_DIR, create_folders
from .http import download_file
from .search import engines
from .types import ENGINE
from .utils import cache_path

__all__ = ["main"]


async def file_hash(file: AsyncPath) -> str:
    hash = xxhash.xxh32()
    async with file.open("rb") as f:
        while chunk := await f.read(4096):
            hash.update(chunk)
    return hash.hexdigest()


async def save_file(file: AsyncPath) -> AsyncPath:
    hash = await file_hash(file)
    new_file = await cache_path(DOWNLOAD_DIR, hash)
    if new_file.exists():
        return new_file
    shutil.copy(str(file), str(new_file))
    return new_file


async def use_engine(
    engine_name: str,
    engine: ENGINE,
    file: AsyncPath,
    session: aiohttp.ClientSession,
    return_cached: bool = True,
) -> dict[str, Any]:
    engine_dir = SEARCH_DIR / engine_name
    search_file = await cache_path(engine_dir, file.with_suffix(".json").name)

    if return_cached and await search_file.exists():
        return json.loads(await search_file.read_text())  # type: ignore[no-any-return]

    try:
        result = await engine(str(file), session)
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
        }
    await search_file.write_text(json.dumps(result))
    return result


async def search(
    file: AsyncPath, session: aiohttp.ClientSession, *, return_cached: bool = True
) -> list[dict[str, Any]]:
    results = await asyncio.gather(
        *(
            use_engine(
                engine_name=name,
                engine=engine,
                file=file,
                session=session,
                return_cached=return_cached,
            )
            for name, engine in engines.items()
        ),
    )
    return results


async def amain(session: aiohttp.ClientSession) -> None:
    parser = ArgumentParser()
    parser.add_argument("file", type=str, help="File or URL to download")
    parser.add_argument(
        "-f", "--force-redownload", action="store_true", help="Force download even if the file already exists"
    )
    parser.add_argument("-R", "--no-return-cached", action="store_true", help="Do not return cached search results")
    args = parser.parse_args()

    await create_folders()

    if os.path.exists(args.file):
        file = await save_file(AsyncPath(args.file))
    else:
        file = await download_file(
            url=args.file, dir=DOWNLOAD_DIR, session=session, force_download=args.force_redownload
        )

    results = await search(file, session, return_cached=not args.no_return_cached)
    print(json.dumps(results, indent=4, sort_keys=True))


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
