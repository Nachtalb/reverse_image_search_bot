from urllib.parse import quote_plus

from cachetools import cached
from requests import Session
from telegram import InlineKeyboardButton
from yarl import URL

from reverse_image_search_bot.settings import SAUCENAO_API

from .generic import GenericRISEngine


class SauceNaoEngine(GenericRISEngine):
    name = 'SauceNAO'
    url = 'https://saucenao.com/search.php?url={query_url}'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = Session()

    @cached(GenericRISEngine._cache)
    def best_match(self, url: str | URL) -> tuple[dict[str, str | int | URL], list[InlineKeyboardButton]]:
        api_link = 'https://saucenao.com/search.php?db=999&output_type=2&testmode=1&numres=3&url={}{}'.format(
            quote_plus(str(url)),
            f'&api_key={SAUCENAO_API}' if SAUCENAO_API else ''
        )
        response = self.session.get(api_link)
        if response.status_code != 200:
            return {}, []

        results = filter(lambda d: float(d['header']['similarity']) >= 75,
                         response.json().get('results', []))

        priority = 21, 5, 9
        datas = [{}, {}, {}]

        for result in results:
            index_id = result['header']['index_id']
            if index_id in priority:
                datas[priority.index(index_id)] = result

        data = {}
        if not list(filter(None, datas)):
            data = next(iter(results), None)
        else:
            for ddata in reversed(list(filter(None, datas))):
                if not data:
                    data = ddata
                else:
                    data['header'].update(ddata['header'])
                    for key, value in list(ddata['data'].items()):
                        orig = data['data'].get(key)
                        if orig is not None and (isinstance(orig, list) or isinstance(value, list)):
                            if not isinstance(value, list):
                                value = [value]
                            if not isinstance(orig, list):
                                orig = [orig]
                            data['data'][key] = value + orig
                        else:
                            data['data'][key] = value

        if not data:
            return {}, []

        buttons = []
        result_data = {
            'thumbnail': URL(data['header']['thumbnail']),
            'source': data['data'].get('source'),
            'part': data['data'].get('part'),
            'similarity': data['header']['similarity'],
            'provider': self.name,
            'provider url': 'https://saucenao.com/'
        }

        if ext_urls := data['data'].get('ext_urls'):
            urls = list(map(URL, ext_urls))
            buttons = [InlineKeyboardButton(text=u.host, url=str(u)) for u in urls]  # type: ignore
            for u in urls:
                result_data[u.host.rsplit('.')[0]] = u  # type: ignore

        if creator := data['data'].get('creator'):
            if isinstance(creator, list) and (creators := list(filter(lambda c: c != ' Unknown', creator))):
                result_data['creators'] = ', '.join(creators)
            else:
                result_data['creators'] = creator

        for key, value in data['data'].items():
            if key not in ['ext_urls', 'creator'] and key not in result_data:
                if (u := URL(str(value))) and u.scheme.startswith('http'):
                    result_data[key] = u
                else:
                    result_data[key] = value

        for key, value in list(result_data.items()):
            if value is None or value == '' or key.endswith('_id') or key.endswith('_aid'):
                del result_data[key]
            if '_' in key and key in result_data:
                result_data[key.replace('_', ' ')] = result_data.pop(key)

        return result_data, buttons
