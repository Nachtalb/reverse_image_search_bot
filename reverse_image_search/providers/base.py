from abc import ABCMeta, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Generic, Literal, Optional, Sequence, TypedDict, TypeVar, Union

from telegram import InlineKeyboardButton
from tgtools.models.summaries import Downloadable, FileSummary
from tgtools.utils.urls.emoji import FALLBACK_EMOJIS, host_emoji, host_name

if TYPE_CHECKING:
    from reverse_image_search.engines.base import SearchEngine


class QueryData(TypedDict):
    pass


T_QueryData = TypeVar("T_QueryData", bound=QueryData)


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
        provider_url (str | tuple[str, str]): The URL of the found media on the provider.
        additional_urls (list[str | tuple[str, str]]): A list of additional URLs related to the message.
        text (dict[str, str | Info | None]): A dictionary containing the text elements of the message.
        file (MediaSummary | None): The main media file sent with the result message.
        additional_files (Sequence[MediaSummary] | None): Max 10 additional media files, sent in a media group
    """

    provider_url: str | tuple[str, str]
    additional_urls: list[str | tuple[str, str]]
    text: dict[str, str | Info | None]
    file: Optional[Union[FileSummary, Downloadable]] = None
    additional_files: Sequence[Union[FileSummary, Downloadable]] = field(default_factory=list)
    additional_files_captions: Sequence[str] | str | None = None

    @property
    def caption(self) -> str:
        return "\n".join(f"<b>{title}:</b> {str(content)}" for title, content in self.text.items() if content)

    @property
    def provider_button(self) -> InlineKeyboardButton:
        if isinstance(self.provider_url, str):
            text = host_name(self.provider_url, with_emoji=True, fallback=FALLBACK_EMOJIS["globe"])
            url = self.provider_url
        else:
            text, url = self.provider_url
            emoji = host_emoji(url, fallback=FALLBACK_EMOJIS["globe"])
            text = f"{emoji} {text}"
        return InlineKeyboardButton(text=text, url=url)

    @property
    def additional_buttons(self) -> list[InlineKeyboardButton]:
        buttons = []
        for url_or_tuple in self.additional_urls:
            if isinstance(url_or_tuple, str):
                text = host_name(url_or_tuple, with_emoji=True, fallback=FALLBACK_EMOJIS["globe"])
                url = url_or_tuple
            else:
                text, url = url_or_tuple
                emoji = host_emoji(url, fallback=FALLBACK_EMOJIS["globe"])
                text = f"{emoji} {text}"
            buttons.append(InlineKeyboardButton(text=text, url=url))

        return buttons


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


class Provider(Generic[T_QueryData], metaclass=ABCMeta):
    """
    Abstract base class for formatters that fetch and format data.

    Attributes:
        name (str): The name of the provider.
        credit_url (str): The URL to the provider's website.
    """

    name: str = "Provider"
    credit_url: str = "https://example.com"

    def provider_info(self, data: T_QueryData | None) -> ProviderInfo:
        """
        Retrieve ProviderInfo based on input data

        Note: For single providers this will just return the configured name and credit_url

        Returns:
            ProviderInfo: Name and URL as ProviderInfo
        """
        return ProviderInfo(self.name, self.credit_url)

    @abstractmethod
    async def provide(self, data: T_QueryData) -> MessageConstruct | None:
        """
        Provide a MessageConstruct with the given information.

        The implementer has to check out how the provider wants the data.

        Args:
            data (TypedDict): A dictionary containing data for the provider to work with.

        Returns:
            MessageConstruct: A object containing all information needed for standardised messages.
        """
        ...
