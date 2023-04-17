from typing import TYPE_CHECKING

from aiohttp import ClientSession

from reverse_image_search.providers.base import Provider

from .ascii2d import Ascii2dSearchEngine
from .base import SearchEngine
from .bing import BingSearchEngine
from .google import GoogleSearchEngine
from .iqdb import Iqdb3DSearchEngine, IqdbSearchEngine
from .saucenao import SauceNaoSearchEngine
from .sogou import SogouSearchEngine
from .tineye import TineyeSearchEngine
from .tracer import TraceSearchEngine
from .yandex import YandexSearchEngine

if TYPE_CHECKING:
    from reverse_image_search.app import ReverseImageSearch


async def initiate_engines(
    session: ClientSession,
    config: "ReverseImageSearch.Arguments",
    providers: dict[str, Provider],
) -> list[SearchEngine]:
    return [
        SauceNaoSearchEngine(config.saucenao.api_key, session, providers),
        GoogleSearchEngine(),
        IqdbSearchEngine(),
        Iqdb3DSearchEngine(),
        TraceSearchEngine(),
        YandexSearchEngine(),
        BingSearchEngine(),
        TineyeSearchEngine(),
        Ascii2dSearchEngine(),
        SogouSearchEngine(),
    ]
