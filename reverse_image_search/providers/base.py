from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Sequence

from tgtools.telegram.compatibility.base import MediaSummary

if TYPE_CHECKING:
    from reverse_image_search.engines.base import SearchEngine


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
    """A data class representing a message construct.

    Attributes:
        provider_url (str): The URL of the found media on the provider.
        additional_urls (list[str]): A list of additional URLs related to the message.
        text (dict[str, str | Info | None]): A dictionary containing the text elements of the message.
        files (MediaSummary | Sequence[MediaSummary] | None): The media files of the message, if available.
    """

    provider_url: str
    additional_urls: list[str]
    text: dict[str, str | Info | None]
    files: MediaSummary | Sequence[MediaSummary] | None

    @property
    def caption(self) -> str:
        return "\n".join(f"<b>{title}:</b> {str(content)}" for title, content in self.text.items() if content)


@dataclass
class ProviderInfo:
    name: str
    credit_url: str


@dataclass
class SearchResult:
    """A data class representing a search result.

    Attributes:
        engine (SearchEngine): The search engine used to obtain the result.
        provider (ProviderInfo): The providers info
        message (MessageConstruct): The message construct associated with the result.
    """

    engine: "SearchEngine"
    provider: ProviderInfo
    message: MessageConstruct

    @property
    def intro(self) -> str:
        """
        Generate an introduction for the search result.

        Returns:
            str: A formatted introduction string.
        """
        return (
            f'Result by <b><a href="{self.engine.credit_url}">{self.engine.name}</a></b> via <b><a'
            f' href="{self.provider.credit_url}">{self.provider.name}</a></b>'
        )

    @property
    def caption(self) -> str:
        """
        Generate a caption for the search result.

        Returns:
            str: A formatted caption string.
        """
        return f"{self.intro}\n\n{self.message.caption}"


class Provider(metaclass=ABCMeta):
    """
    Abstract base class for formatters that fetch and format data.

    Attributes:
        name (str): The name of the provider.
        credit_url (str): The URL to the provider's website.
    """

    name: str = "Provider"
    credit_url: str = "https://example.com"

    def provider_info(self, data: dict[str, Any] | None) -> ProviderInfo:
        """
        Retrieve ProviderInfo based on input data

        Note: For single providers this will just return the configured name and credit_url

        Returns:
            ProviderInfo: Name and URL as ProviderInfo
        """
        return ProviderInfo(self.name, self.credit_url)

    @abstractmethod
    async def provide(self, data: dict[str, Any]) -> MessageConstruct | None:
        """
        Provide a MessageConstruct with the given information.

        The implementer has to check out how the provider wants the data.

        Args:
            data (dict[str, Any]): A dictionary containing data for the provider to work with.

        Returns:
            MessageConstruct: A object containing all information needed for standardised messages.
        """
        ...
