from .base import SearchEngine
from .google import GoogleSearchEngine
from .saucenao import SauceNaoSearchEngine

engines: list[SearchEngine] = [GoogleSearchEngine(), SauceNaoSearchEngine()]
