from aiopath import AsyncPath


async def cache_path(dir: AsyncPath, name: str) -> AsyncPath:
    cache_dir = dir / name[:2]
    await cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / name
