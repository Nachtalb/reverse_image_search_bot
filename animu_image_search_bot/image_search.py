import logging
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
