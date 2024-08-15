import xxhash
from aiohttp import ClientSession
from aiopath import AsyncPath

from .utils import cache_path

__all__ = ["download_file"]


async def download_file(url: str, dir: AsyncPath, session: ClientSession, *, force_download: bool = False) -> AsyncPath:
    """Download a file from a URL.

    Note:
        The file is saved with a name based on the URL hash. No file extension is added.

    Args:
        url (:obj:`str`): The URL to download the file from.
        dir (:obj:`aiopath.AsyncPath`): The directory to download the file to.
        session (:obj:`aiohttp.ClientSession`): The aiohttp session to use.
        force_download (:obj:`bool`, optional): Whether to force the download even if the file already exists.

    Returns:
        :obj:`aiopath.AsyncPath`: The path to the downloaded file.

    Raises:
        :obj:`ValueError`: If the MIME type of the file cannot be determined.
    """
    hash = xxhash.xxh32(url.encode())
    digest = hash.hexdigest()

    new_name = f"{digest}"
    file = await cache_path(dir, new_name)

    if not force_download and await file.is_file():
        return file

    async with session.get(url) as response:
        response.raise_for_status()

        async with file.open("wb") as file_obj:
            async for chunk in response.content.iter_any():
                await file_obj.write(chunk)

        return file
