import logging
from urllib.parse import quote_plus

from yarl import URL
from telegram import InlineKeyboardButton


class GenericRISEngine:
    name: str = 'GenericRISEngine'
    url: str = ''

    def __init__(self, name: str = None, url: str = None):
        self.name = name or self.name
        self.url = url or self.url
        self.logger = logging.getLogger('RISEngine [{self.name}]')

    def __call__(self, url: str | URL) -> InlineKeyboardButton:
        """Create the :obj:`InlineKeyboardButton` button for the telegram but to use

        Args:
            url (:obj:`str` | :obj:`URL`): Url of the uploaded medium

        Returns:
            :obj:`InlineKeyboardButton`: Telegram button with name and url target
        """
        return InlineKeyboardButton(text=self.name,
                                    url=str(self.get_search_link_by_url(url)))

    def get_search_link_by_url(self, url: str | URL) -> URL:
        """Get the reverse image search link for the given url

        Args:
            url (:obj:`str`): Link to the image

        Returns:
            :obj:`URL`: Generated reverse image search engine for the given image
        """
        return URL(self.url.format(query_url=quote_plus(str(url))))

    def best_match(self, url: str | URL) -> dict:
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
        """
        return {}
