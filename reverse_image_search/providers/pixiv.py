from io import BytesIO
from pathlib import Path
from typing import Any

from aiopixiv._api import PixivAPI
from emoji import emojize
from pydantic import BaseModel
from tgtools.models.file_summary import FileSummary
from tgtools.telegram.text import tagified_string
from yarl import URL

from reverse_image_search.providers.base import Info, MessageConstruct, Provider


class PixivProvider(Provider):
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

    async def provide(self, data: dict[str, Any]) -> MessageConstruct | None:
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

        urls = [page.image_urls.best for page in post.meta_pages][:10]
        files = [BytesIO() for _ in range(len(post.meta_pages[:10]))]
        mapping = {id(file): (i, page) for i, (page, file) in enumerate(zip(post.meta_pages[:10], files))}

        summaries = []
        async for file in post.get_client().download_many(urls=urls, files=files):
            index, page = mapping[id(file)]
            extension = URL(page.image_urls.best).name.rsplit(".", 1)[-1]
            summaries.append(
                FileSummary(
                    file=file,
                    file_name=Path(f"pixiv_{post.id}_p{index}.{extension}"),
                    height=0,
                    width=0,
                    size=len(file.getvalue()),
                )
            )

        return MessageConstruct(
            provider_url=str(source_url),
            additional_urls=[
                artist_url,
            ],
            files=summaries,
            text=text,
        )
