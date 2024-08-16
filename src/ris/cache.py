import json
from pathlib import Path

from aiopath import AsyncPath

from .defaults import DOWNLOAD_DIR, SEARCH_DIR, SOURCE_DIR
from .types import Errored, Normalized, SourceDict

__all__ = ["DOWNLOAD_CACHE", "SEARCH_CACHE", "SOURCE_CACHE", "Cache", "JsonCache"]


class Cache:
    def __init__(self, dir: str | Path | AsyncPath) -> None:
        self.dir = AsyncPath(dir)

    async def cache_path(self, name: str, sub_dir: AsyncPath | None = None, *, _create: bool = False) -> AsyncPath:
        dir_ = self.dir
        if sub_dir:
            dir_ = self.dir / sub_dir

        cache_dir = dir_ / name[:2]
        if _create:
            await cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / name

    async def exists(self, name: str, sub_dir: AsyncPath | None = None) -> bool:
        return await (await self.cache_path(name, sub_dir=sub_dir)).exists()  # type: ignore[no-any-return]

    async def get(self, name: str, sub_dir: AsyncPath | None = None) -> str:
        return await (await self.cache_path(name, sub_dir=sub_dir)).read_text()  # type: ignore[no-any-return]

    async def set(self, name: str, data: str, sub_dir: AsyncPath | None = None) -> None:
        await (await self.cache_path(name, _create=True, sub_dir=sub_dir)).write_text(data)


class JsonCache[CacheType](Cache):
    async def get_json(self, name: str, sub_dir: AsyncPath | None = None) -> CacheType:
        return json.loads(await self.get(name, sub_dir=sub_dir))  # type: ignore[no-any-return]

    async def set_json(self, name: str, data: CacheType, sub_dir: AsyncPath | None = None) -> None:
        await self.set(name, json.dumps(data), sub_dir=sub_dir)


DOWNLOAD_CACHE = Cache(DOWNLOAD_DIR)
SEARCH_CACHE = JsonCache[list[Normalized] | Errored](SEARCH_DIR)
SOURCE_CACHE = JsonCache[SourceDict | None](SOURCE_DIR)
