from abc import ABCMeta, abstractmethod
from typing import Any, Literal, Type
from dataclasses import dataclass

from telegram import Document, PhotoSize, Video
from tgtools.telegram.compatibility.base import MediaSummary


@dataclass
class Info:
    text: str
    type: Literal["code", "bold", "italic"] | None = None
    url: str = ""

    def __str__(self) -> str:
        text = self.text
        if self.url:
            text = f'<a href="{self.url}">{text}</a>'

        match self.type:
            case "code":
                text = f"<code>{text}</code>"
            case "bold":
                text = f"<b>{text}</bg"
            case "italic":
                text = f"<i>{text}</i>"
            case _:
                pass
        return text


@dataclass
class MessageConstruct:
    type: Type[Document] | Type[Video] | Type[PhotoSize] | None
    source_url: str
    additional_urls: list[str]
    text: dict[str, str | Info | None]
    file: MediaSummary | None

    @property
    def caption(self) -> str:
        return "\n".join(f"<b>{title}:</b> {str(content)}" for title, content in self.text.items() if content)


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
