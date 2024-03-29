from typing import TYPE_CHECKING, Any

from aiohttp import ClientSession

from reverse_image_search.providers.base import Provider
from reverse_image_search.providers.booru import BooruProvider
from reverse_image_search.providers.pixiv import PixivProvider

if TYPE_CHECKING:
    from reverse_image_search.app import ReverseImageSearch


async def initiate_data_providers(
    session: ClientSession, config: "ReverseImageSearch.Arguments"
) -> dict[str, Provider[Any]]:
    return {
        "booru": BooruProvider(session, config.boorus),
        "pixiv": PixivProvider(config.pixiv),
    }
