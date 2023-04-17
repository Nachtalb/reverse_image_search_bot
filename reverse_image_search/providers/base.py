from abc import ABCMeta, abstractmethod
from typing import Any, Type
from dataclasses import dataclass

from telegram import Document, PhotoSize, Video
from tgtools.telegram.compatibility.base import MediaSummary


@dataclass
class MessageConstruct:
    type: Type[Document] | Type[Video] | Type[PhotoSize] | None
    caption: str
    source_url: str
    additional_urls: list[str]
    file: MediaSummary | None


class Provider(metaclass=ABCMeta):
    """
    Abstract base class for formatters that fetch and format data.
    """

    @abstractmethod
    async def provide(self, data: dict[str, Any]) -> MessageConstruct:
        """
        Provide a MessageConstruct with the given information.

        The implementer has to check out how the provider wants the data.

        Args:
            data (dict[str, Any]): A dictionary containing data for the provider to work with.

        Returns:
            MessageConstruct: A object containing all information needed for standardised messages.
        """
        ...
