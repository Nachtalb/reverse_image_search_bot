import logging
import re
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from requests import HTTPError


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

    def upload_image(self, image_file):
        """Upload the given image to a image hoster

        At the moment bayimg.com is used as a hoster. In the future this may change.

        Args:
            image_file: File like object of an image
        Returns:
            :obj:`str`: Url to the uploaded image
        Raises:
            TypeError: If the given image is not a file like object
            HTTPError: If the server sent a response with an status code other than 200
            Exception: If we know there was an error but we do not know why
        """
        if not hasattr(image_file, 'read'):
            error_message = 'Given object is not a file ot file like object. "read()" method must be integrated.'
            self.logger.warning(error_message)
            raise TypeError(error_message)

        if hasattr(image_file, 'seek'):
            image_file.seek(0)

        url_base = 'http://bayimg.com'
        upload_path = '/upload'

        data_payload = {'code': 'removal_code_must_be_set_on_bayimg'}
        files_payload = {'file': image_file}

        response = requests.request("POST", (url_base + upload_path), data=data_payload, files=files_payload)

        if response.status_code != 200:
            error_message = ('Could not upload image. Instead of expected 200 response, we got a %s status code.' %
                             response.status_code)
            self.logger.warning(error_message)
            raise HTTPError(error_message, response=response)

        soup = BeautifulSoup(response.text, "html.parser")
        image = soup.find('img', {'class': 'image-setting'})

        if image:
            return url_base + image['src'][2:]
        error_message = 'Cold not upload image because of an unknown error.'
        self.logger.warning(error_message)
        raise Exception(error_message)

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
        if url == self.search_url and self.search_html != '':
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
                'SIMILARITY': float 'SIMILARITY_IN_%_TO_ORIGINAL'
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
        best_match = {
            'thumbnail': self.url_base + table.select('td.image img')[0].attrs['src'],
            'website': table.select('td.image a')[0].attrs['href'],
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
