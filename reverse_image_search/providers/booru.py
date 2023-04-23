from typing import Any

from aiohttp import BasicAuth, ClientSession
from emoji import emojize
from pydantic import BaseModel
from tgtools.api import DanbooruApi, YandereApi
from tgtools.models import RATING
from tgtools.telegram.text import tagified_string

from reverse_image_search.providers.base import Info, MessageConstruct, Provider, ProviderInfo


class BooruProvider(Provider):
    """A provider for fetching and processing booru posts.

    Attributes:
        danbooru (DanbooruApi): An instance of the DanbooruApi class.
        yandere (YandereApi): An instance of the YandereApi class.
    """

    name = "Booru"

    class Config(BaseModel):
        """Configuration for the BooruProvider.

        Attributes:
            danbooru_username (str): The username for accessing the Danbooru API.
            danbooru_api_key (str): The API key for accessing the Danbooru API.
        """

        danbooru_username: str
        danbooru_api_key: str

    def __init__(self, session: ClientSession, config: "Config") -> None:
        """
        Initialise the BooruProvider with a session and configuration.

        Args:
            session (ClientSession): The aiohttp ClientSession to be used for API calls.
            config (Config): The configuration object containing API credentials.
        """
        self.danbooru = DanbooruApi(session, BasicAuth(config.danbooru_username, config.danbooru_api_key))
        self.yandere = YandereApi(session)

    def provider_info(self, data: dict[str, Any] | None) -> ProviderInfo:
        """
        Fetch and process a booru post.

        Args:
            data (dict[str, Any]): A dictionary containing the provider name and post ID.

        Returns:
            MessageConstruct | None: A MessageConstruct object containing the processed image
                                     data or None if the provider is not supported.
        """
        if not data:
            return super().provider_info(data)

        match data["provider"]:
            case "danbooru":
                return ProviderInfo("Danbooru", str(self.danbooru.url))
            case "yandere":
                return ProviderInfo("Yandere", str(self.yandere.url))
            case _:
                return super().provider_info(data)

    async def provide(self, data: dict[str, Any]) -> MessageConstruct | None:
        """
        Fetch and process a booru post.

        Args:
            data (dict[str, Any]): A dictionary containing the provider name and post ID.

        Returns:
            MessageConstruct | None: A MessageConstruct object containing the processed image
                                     data or None if the provider is not supported.

        Examples:
            # Fetch a post from Danbooru with ID 12345
            data = {"provider": "danbooru", "id": 12345}
            message_construct = await booru_provider.provide(data)

            # Fetch a post from Yandere with ID 67890
            data = {"provider": "yandere", "id": 67890}
            message_construct = await booru_provider.provide(data)
        """
        match data["provider"]:
            case "danbooru":
                provider = self.danbooru
            case "yandere":
                provider = self.yandere
            case _:
                return None

        post_id: int = data["id"]

        post = await provider.post(post_id)

        if post is None:
            return None

        text: dict[str, str | Info | None] = {
            "Rating": None,
            "Artist": tagified_string(post.tags_artist),
            "Tags": tagified_string(post.tags, 10),
            "Characters": tagified_string(post.tags_character),
            "Copyright": tagified_string(post.tags_copyright),
        }
        if post.rating:
            rating_emoji = emojize(":no_one_under_eighteen:" if RATING.level(post.rating) > 1 else ":cherry_blossom:")
            text["Rating"] = Info(f"{rating_emoji} {post.rating_simple}", "code")

        source_url = post.main_source

        return MessageConstruct(
            provider_url=str(post.url),
            additional_urls=[source_url] if source_url else [],
            file=post.file_summary,
            text=text,
        )
