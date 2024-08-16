import shutil

import xxhash
from aiopath import AsyncPath

from .cache import DOWNLOAD_CACHE

__all__ = ["file_hash", "save_file"]


async def file_hash(file: AsyncPath) -> str:
    hash = xxhash.xxh32()
    async with file.open("rb") as f:
        while chunk := await f.read(4096):
            hash.update(chunk)
    return hash.hexdigest()


async def save_file(file: AsyncPath, use_cache: bool = True) -> AsyncPath:
    hash = await file_hash(file)
    new_file = await DOWNLOAD_CACHE.cache_path(hash)
    if use_cache and await new_file.exists():
        return new_file
    shutil.copy(str(file), str(new_file))
    return new_file
