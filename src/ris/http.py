import xxhash
from aiohttp import ClientSession
from aiopath import AsyncPath

from .cache import DOWNLOAD_CACHE

__all__ = ["download_file"]


async def download_file(url: str, dir: AsyncPath, session: ClientSession, *, use_cache: bool = True) -> AsyncPath:
    """Download a file from a URL.

    Note:
        The file is saved with a name based on the URL hash. No file extension is added.

    Args:
        url (:obj:`str`): The URL to download the file from.
        dir (:obj:`aiopath.AsyncPath`): The directory to download the file to.
        session (:obj:`aiohttp.ClientSession`): The aiohttp session to use.
        use_cache (:obj:`bool`): Whether to use the download cache.

    Returns:
        :obj:`aiopath.AsyncPath`: The path to the downloaded file.

    Raises:
        :obj:`ValueError`: If the MIME type of the file cannot be determined.
    """
    hash = xxhash.xxh32(url.encode())
    digest = hash.hexdigest()

    new_name = f"{digest}"
    file = await DOWNLOAD_CACHE.cache_path(new_name, _create=True)

    if use_cache and await file.is_file():
        return file

    async with session.get(url) as response:
        response.raise_for_status()

        async with file.open("wb") as file_obj:
            async for chunk in response.content.iter_any():
                await file_obj.write(chunk)

        return file
