import logging
import os
import re
from importlib import import_module
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from telegram import InlineKeyboardButton

from reverse_image_search_bot.settings import UPLOADER

uploader_pkg_name, uploader_class_name = UPLOADER['uploader'].rsplit('.', 1)
uploader_module = import_module(uploader_pkg_name)
uploader_class = getattr(uploader_module, uploader_class_name)
uploader = uploader_class(UPLOADER['configuration'])


class ReverseImageSearchEngine:
    """The base class for reverse image search engines to inherit from.

    Attributes:
        url_base (:obj:`str`): The base url of the image search engine eg. `https://www.google.com`
        url_path (:obj:`str`): The url path to the actual reverse image search function. The google url would look like
            this: `/searchbyimage?&image_url={image_url}`
        name (:obj:`str`): Name of thi search engine
        search_html (:obj:`str`): The html of the last searched image
        search_url (:obj:`str`): The image url of the last searched image

    Args:
        url_base (:obj:`str`): The base url of the image search engine eg. `https://www.google.com`
        url_path (:obj:`str`): The url path to the actual reverse image search function. It must contain `{image_url}`,
            in which the url to the image will be placed. The google url would look like this:
            `/searchbyimage?&image_url={image_url}`
        name (:obj:`str`, optional): Give the Search engine a name if you want
    """
    name = 'Base Reverse Image Search Engine'
    logger = logging.getLogger(__name__)

    search_html = None
    search_url = None

    def __init__(self, url_base, url_path, name=None):
        self.url_base = url_base
        self.url_path = url_path
        self.name = name

    def button(self, url):
        url = self.get_search_link_by_url(url)
        return InlineKeyboardButton(text=self.name, url=url)

    def get_search_link_by_url(self, url):
        """Get the reverse image search link for the given url

        Args:
            url (:obj:`str`): Link to the image

        Returns:
            :obj:`str`: Generated reverse image search engine for the given image
        """
        self.search_url = url
        self.search_html = ''
        return self.url_base + self.url_path.format(image_url=quote_plus(url))

    def get_search_link_by_file(self, file_):
        """Get the reverse image search link for the given file

        Args:
            file_: File like object

        Returns:
            :obj:`str`: Generated reverse image search engine for the given image
        """
        return self.get_search_link_by_url(self.upload_image(file_))

    def upload_image(self, image_file, file_name: str = None):
        """Upload the given image to the in the settings specified place.

        Args:
            image_file: File like object of an image or path to an image
            file_name (:obj:`str`): Name of the given file. Can be left empty if image_file is a file path
        Returns:
            :obj:`str`: Url to the uploaded image
        Raises:
            ValueError: If the image_file is an file like object and the file_name has not been set.
        """
        if not file_name:
            if not isinstance(image_file, str):
                error_message = 'When image_file is a file like object the file_name must be set.'
                self.logger.warning(error_message)
                raise ValueError(error_message)
            file_name = os.path.basename(image_file)

        uploader.connect()
        uploader.upload(image_file, file_name)
        uploader.close()

        path = UPLOADER.get('url', None) or UPLOADER['configuration'].get('path', None) or ''
        return os.path.join(path, file_name)

    def get_html(self, url=None):
        """Get the HTML of the image search site.

        Args:
            url (:obj:`str`): Link to the image, if no url is given it takes the last searched image url

        Returns:
            :obj:`str`: HTML of the image search site

        Raises:
            ValueError: If no url is defined and no last_searched_url is available
        """
        if not url:
            if not self.search_url:
                raise ValueError('No url defined and no last_searched_url available!')
            url = self.search_url
        if url == self.search_url and self.search_html:
            return self.search_html

        request = requests.get(self.get_search_link_by_url(url))
        self.search_html = request.text
        return self.search_html

    @property
    def best_match(self):
        """Get info about the best matching image found

        Notes:
            This function must be individually made for every new search engine. This is because every search engine
            gives other data. Normally the return value should look something like this:
            ```
            {
                'thumbnail': str 'LINK_TO_THUMBNAIL',
                'website': str 'LINK_TO_FOUND_IMAGE',
                'website_name': str 'NAME_OF_WEBSITE_IMAGE_FOUND_ON',
                'size': {
                    'width': int 'IMAGE_WIDTH',
                    'height': int 'IMAGE_HEIGHT'
                },
                'similarity': float 'SIMILARITY_IN_%_TO_ORIGINAL'
            }
            ```

        Returns:
            :obj:`dict`: Dictionary of the found image

        Raises:
            ValueError: If not image was given to this class yet
        """
        return None


class GoogleReverseImageSearchEngine(ReverseImageSearchEngine):
    """A :class:`ReverseImageSearchEngine` configured for google.com"""

    def __init__(self):
        super(GoogleReverseImageSearchEngine, self).__init__(
            url_base='https://www.google.com',
            url_path='/searchbyimage?&image_url={image_url}',
            name='Google'
        )


class IQDBReverseImageSearchEngine(ReverseImageSearchEngine):
    """A :class:`ReverseImageSearchEngine` configured for iqdb.org"""

    def __init__(self):
        super(IQDBReverseImageSearchEngine, self).__init__(
            url_base='http://iqdb.org',
            url_path='?url={image_url}',
            name='iqdb'
        )

    @property
    def best_match(self):
        if not self.search_html:
            if not self.search_url:
                raise ValueError('No image given yet!')
            self.get_html(self.search_url)
        soup = BeautifulSoup(self.search_html, "html.parser")
        best_match = soup.find('th', text='Best match')

        if not best_match:
            return
        table = best_match.find_parent('table')
        size_match = re.match('\d*×\d*', table.find('td', text=re.compile('×')).text)
        size = size_match[0]
        safe = size_match.string.replace(size, '').strip(' []')

        website = table.select('td.image a')[0].attrs['href']
        if not website.startswith('http'):
            website = 'http://' + website.lstrip('/ ')
        best_match = {
            'thumbnail': self.url_base + table.select('td.image img')[0].attrs['src'],
            'website': website,
            'website_name': table
                .find('img', {'class': 'service-icon'})
                .find_parent('td')
                .find(text=True, recursive=False)
                .strip(),
            'size': {
                'width': int(size.split('×')[0]),
                'height': int(size.split('×')[1])
            },
            'sfw': safe,
            'similarity': float(re.match('\d*', table.find('td', text=re.compile('similarity')).text)[0]),
            'provided by': '[IQDB](http://iqdb.org/)',
        }

        return best_match


class TinEyeReverseImageSearchEngine(ReverseImageSearchEngine):
    """A :class:`ReverseImageSearchEngine` configured for tineye.com"""

    def __init__(self):
        super(TinEyeReverseImageSearchEngine, self).__init__(
            url_base='https://tineye.com',
            url_path='/search?url={image_url}',
            name='TinEye'
        )

    @property
    def best_match(self):
        """

        Returns:

        """
        if not self.search_html:
            if not self.search_url:
                raise ValueError('No image given yet!')
            self.get_html(self.search_url)
        soup = BeautifulSoup(self.search_html, 'html.parser')

        match = soup.find('div', {'class', 'match'})
        if not match:
            return
        image_url = match.find('p', {'class': 'image-link'}).find('a').get('href')

        if not self.check_image_availability(image_url):
            match = match.find_next('div', {'class', 'match'})
            if not match:
                return
            image_url = match.find('p', {'class': 'image-link'}).find('a').get('href')
            if not self.check_image_availability(image_url):
                return

        match_row = match.find_parent('div', {'class': 'match-row'})
        match_thumb = match_row.find('div', {'class': 'match-thumb'})
        info = match_thumb.find('p').text
        info = [element.strip() for element in info.split(',')]

        return {
            'thumbnail': match_thumb.find('img').get('src'),
            'website_name': match.find('h4').text,
            'website': match.find('span', text='Found on: ').find_next('a').get('href'),
            'image_url': image_url,
            'type': info[0],
            'size': {
                'width': int(info[1].split('x')[0]),
                'height': int(info[1].split('x')[1])
            },
            'volume': info[2],
            'provided by': '[TinEye](https://tineye.com/)',
        }

    def check_image_availability(self, url: str):
        """Check if image is still available

        Args:
            url (:obj:`str`): Url to image to check
        """
        try:
            return requests.head(url) == 200
        except:
            pass


class BingReverseImageSearchEngine(ReverseImageSearchEngine):
    """A :class:`ReverseImageSearchEngine` configured for bing.com"""

    def __init__(self):
        super(BingReverseImageSearchEngine, self).__init__(
            url_base='https://www.bing.com',
            url_path='/images/search?q=imgurl:{image_url}&view=detailv2&iss=sbi',
            name='Bing'
        )


class YandexReverseImageSearchEngine(ReverseImageSearchEngine):
    """A :class:`ReverseImageSearchEngine` configured for yandex.com"""

    def __init__(self):
        super(YandexReverseImageSearchEngine, self).__init__(
            url_base='https://yandex.com',
            url_path='/images/search?url={image_url}&rpt=imageview',
            name='Yandex'
        )

class SauceNaoReverseImageSearchEngine(ReverseImageSearchEngine):
    """A :class:`ReverseImageSearchEngine` configured for saucenao.com"""

    def __init__(self):
        super(SauceNaoReverseImageSearchEngine, self).__init__(
            url_base='https://saucenao.com',
            url_path='/search.php?url={image_url}',
            name='SauceNao'
        )


class TraceReverseImageSearchEngine(ReverseImageSearchEngine):
    """A :class:`ReverseImageSearchEngine` configured for trace.moe
    """

    def __init__(self):
        super(TraceReverseImageSearchEngine, self).__init__(
            url_base='https://trace.moe',
            url_path='/?auto&url={image_url}',
            name='Trace'
        )
