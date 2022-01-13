from cachetools import cached
from telegram import InlineKeyboardButton
from requests import Session
from yarl import URL

from .generic import GenericRISEngine


class TraceEngine(GenericRISEngine):
    name = 'Trace'
    url = 'https://trace.moe/?auto&url={query_url}'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = Session()

    @cached(GenericRISEngine._cache)
    def best_match(self, url: str | URL) -> tuple[dict[str, str | int | URL], list[InlineKeyboardButton]]:
        return {}, []
        return {
            'link': link,
            'site_name': site_name,
            'thumbnail': thumbnail,
            'size': f'{width}x{height}',
            'width': width,
            'height': height,
            'rating': rating,
            'similarity': similarity,
            'provider': 'IQDB',
            'provider_url': 'https://iqdb.org/'
        }

