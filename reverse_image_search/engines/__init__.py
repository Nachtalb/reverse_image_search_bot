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

engines: list[SearchEngine] = [
    SauceNaoSearchEngine(),
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
