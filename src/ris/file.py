import logging
import shutil

import xxhash
from aiopath import AsyncPath

from .cache import DOWNLOAD_CACHE

__all__ = ["file_hash", "save_file"]

log = logging.getLogger(__name__)


async def file_hash(file: AsyncPath) -> str:
    log.debug(f"Hashing {file}")
    hash = xxhash.xxh32()
    async with file.open("rb") as f:
        while chunk := await f.read(4096):
            hash.update(chunk)
    return hash.hexdigest()


async def save_file(file: AsyncPath, use_cache: bool = True) -> AsyncPath:
    log.debug(f"Saving {file}")
    log.debug(f"Use cache: {use_cache}")
    hash = await file_hash(file)
    new_file = await DOWNLOAD_CACHE.cache_path(hash)
    if use_cache and await new_file.exists():
        log.info(f"Using cached file: {new_file}")
        return new_file
    log.info(f"Saving file to {new_file}")
    shutil.copy(str(file), str(new_file))
    return new_file
