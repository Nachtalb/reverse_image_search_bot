import re

from requests_html import HTMLSession
from yarl import URL

from .generic import GenericRISEngine


class IQDBEngine(GenericRISEngine):
    name = 'IQDB'
    url = 'https://iqdb.org/?url={query_url}'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = HTMLSession()

    def best_match(self, url: str | URL):
        response = self.session.get(str(self.get_search_link_by_url(url)))

        if response.status_code != 200:
            return {}

        best_match = response.html.find('th', text='Best match')

        if not best_match:
            return {}

        rows = best_match.find_parent('table td')

        link = URL(rows[0].find('a')[0].attrs['href']).with_scheme('https')
        thumbnail = URL(self.url).with_path(rows[0].find('img')[0].attrs['src'])
        site_name = rows[1].find(text=True, recursive=False).strip()

        match = re.match(r'(\d+)×(\d+) \[(\w+)\]', rows[2].text)
        width, height, rating = match.groups()
        width, height = int(width), int(height)

        similarity = int(re.match(r'\d+', rows[3].text)[0])


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
