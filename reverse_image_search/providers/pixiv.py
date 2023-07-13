from pathlib import Path
from typing import Optional

from aiopixiv._api import PixivAPI
from emoji import emojize
from pydantic import BaseModel
from tgtools.models.summaries import ToDownload
from tgtools.telegram.text import tagified_string
from yarl import URL

from reverse_image_search.providers.base import Info, MessageConstruct, Provider, QueryData


class PixivQuery(QueryData):
    id: int
    image_index: Optional[int]


class PixivProvider(Provider[PixivQuery]):
    """A provider for fetching and processing pixiv illustrations."""

    name = "Pixiv"
    credit_url = "http://pixiv.net"

    class Config(BaseModel):
        """Configuration for the PixivProvider

        Attributes:
            access_token (str): API JWT access token
            refresh_token (str): API JWT refresh token
        """

        access_token: str
        refresh_token: str

    def __init__(self, config: "Config") -> None:
        """
        Initialise the PixivProvider with a session and configuration.

        Args:
            config (Config): The configuration object containing API credentials.
        """
        self.client = PixivAPI(access_token=config.access_token, refresh_token=config.refresh_token)

    async def provide(self, data: PixivQuery) -> MessageConstruct | None:
        """
        Fetch and process a pixiv illustration.

        Args:
            data (dict[str, Any]): A dictionary containing the post id with "id"

        Returns:
            MessageConstruct | None: A MessageConstruct object containing the processed image
                                     data or None if the provider is not supported.

        Examples:
            # Fetch a post with ID 67890
            data = {"id": 67890}
            message_construct = await pixiv_provider.provide(data)
        """
        post_id: int = data["id"]

        post = await self.client.illust(post_id)

        if post is None:
            return None

        rating_emoji = emojize(":no_one_under_eighteen:" if post.x_restrict else ":cherry_blossom:")
        rating_text = "R-18" if post.x_restrict else "Safe"

        text: dict[str, str | Info | None] = {
            "Title": post.title,
            "Artist": f"{post.user.name} ({tagified_string(post.user.account)})",
            "Artworks in post": f"{len(post.meta_pages)}",
            "Size": f"{post.width}x{post.height}",
            "Rating": f"{rating_emoji} {rating_text}",
            "Tags": ", ".join(
                [
                    tag.name + (f" / {tagified_string(tag.translated_name)}" if tag.translated_name else "")
                    for tag in post.tags
                ]
            ),
        }
        source_url = f"https://www.pixiv.net/en/artworks/{post.id}"
        artist_url = f"https://www.pixiv.net/en/user/{post.user.id}"

        client = post.get_client()
        main_file = ToDownload(
            url=post.meta_pages[data["image_index"] or 0].image_urls.best,
            download_method=client.download,
        )

        additional_files_captions = None
        additional_files = []
        if len(pages := post.meta_pages[:10]) > 1:
            for index, page in enumerate(pages):
                url = page.image_urls.best
                additional_files.append(
                    ToDownload(
                        url=url,
                        download_method=client.download,
                        filename=f"p_{post.id}_p{index}" + Path(URL(url).name).suffix,
                    )
                )

            if len(post.meta_pages) > 10:
                additional_files_captions = [
                    f"Theser are the first 10 illustrations out of {len(post.meta_pages)} in the post."
                ]

        return MessageConstruct(
            provider_url=str(source_url),
            additional_urls=[
                artist_url,
            ],
            text=text,
            file=main_file,
            additional_files=additional_files,
            additional_files_captions=additional_files_captions,
        )
