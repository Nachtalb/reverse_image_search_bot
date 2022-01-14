from logging import getLogger
from pathlib import Path
from typing import IO

from yarl import URL

from reverse_image_search_bot.settings import UPLOADER


class UploaderBase:
    """Base class for other uploader's to inherit from to ensure to use the same methods and attributes.

    Attributes:
        configuration (:obj:`dict`): Configuration of this uploader
    Args:
        configuration (:obj:`dict`): Configuration of this uploader
        connect (:obj:`bool`): If the uploader should directly connect to the server
    """

    _mandatory_configuration = {}
    """(:obj:`dict`): Mandatory configuration settings.

    Usage:
        {'some_key': type}:
            - 'some_key' is a key name like 'host'
            - type is a python object like :class:`str`
    """

    def __init__(self, configuration: dict, connect: bool = False):
        self.logger = getLogger(self.__class__.__name__)
        for key, type_ in self._mandatory_configuration.items():
            if key not in configuration:
                raise KeyError('Configuration must contain key: "%s"' % key)
            if not isinstance(configuration[key], type_):
                raise TypeError('Configuration key "%s" must be instance of "%s"' % (key, type_))

        self.configuration = configuration
        if connect:
            self.connect()
        self.logger.info("Initialised")

    def __enter__(self):
        self.connect()

    def __exit__(self, *_):
        self.close()

    def connect(self):
        """Connect to the server defined in the configuration"""
        pass

    def close(self):
        """Close connection to the server"""
        pass

    def upload(self, file: IO | Path, file_name: str):
        """Upload a file to the server

        Args:
            file: file like object or a path to a file
            file_name: the file name to be used at the destination
        """
        raise NotImplementedError()

    def file_exists(self, file_name: str) -> bool:
        """Check if the file already exists"""
        return False

    def get_url(self, file_name: str) -> URL:
        return URL(UPLOADER["url"]) / file_name
