import asyncio
import re
from io import BytesIO
from pathlib import Path

from emoji import emojize
from pixivpy3 import AppPixivAPI
from yarl import URL

from reverse_image_search_bot.config.pixiv_config import PixivConfig
from reverse_image_search_bot.engines.types import InternalProviderData, MetaData
from reverse_image_search_bot.utils import tagify, upload_file, url_button
from reverse_image_search_bot.utils.async_cache import async_provider_cache

from .base import BaseProvider


class PixivProvider(BaseProvider):
    info = {
        "name": "Pixiv",
        "url": "https://www.pixiv.net/",
        "types": ["Anime", "Manga"],
        "site_type": "Artist Board",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = PixivConfig()
        self.api = AppPixivAPI()
        try:
            self.api.auth(refresh_token=self.config.refresh_token)
        except Exception as error:
            self.logger.exception(error)
            self.logger.warning("Could not authenticate with pixiv")
            self.authenticated = False
            return

        self.config.refresh_token = self.api.refresh_token
        self.config.access_token = self.api.access_token
        self.authenticated = True

    @async_provider_cache
    async def request(self, illust_id: int | str):
        if isinstance(illust_id, str):
            if illust_id.isdigit():
                illust_id = int(illust_id)
            else:
                if reg_match := re.search(r"artworks\/(\d+)", illust_id):
                    illust_id = int(reg_match.groups()[0])
                else:
                    return None
        # pixivpy3 is sync, run in thread to not block
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, self.api.illust_detail, illust_id)
        if data.error:
            if "Error Message: invalid_grant" in data.error.message:
                await loop.run_in_executor(None, self.api.auth)  # Refresh token which dies after 1h
                return await self.request(illust_id)
            self.logger.warning(f"Could not retrieve data: {data.error.user_message or data.error.message}")
            return None
        return data.illust

    async def _images(self, data) -> list[URL]:
        image_urls = []
        if 1 < data.page_count < 11:
            for image in data.meta_pages:
                image_urls.append(image.image_urls)
        else:
            image_urls.append(data.image_urls)

        urls = []
        get_original = data.width + data.height < 10000
        for index, image in enumerate(image_urls):
            url = image.get("large", image.get("medium"))
            if get_original:
                url = image.get("original", url)
            urls.append((url, data.id, index))

        # Download images concurrently via thread pool (pixivpy3 is sync)
        loop = asyncio.get_running_loop()
        tasks = [loop.run_in_executor(None, self._download_image, url_data) for url_data in urls]
        results = await asyncio.gather(*tasks)
        return [img for img in results if img]

    def _download_image(self, url_data: tuple[str, int, int]) -> URL:
        url, post_id, index = url_data
        with BytesIO() as out:
            self.api.download(url, fname=out)
            return upload_file(out, file_name=f"{post_id}_p{index}{Path(url).name}")

    async def provide(self, illust_id: int | str) -> InternalProviderData:
        if not self.authenticated:
            return {}, {}

        data = await self.request(illust_id)
        if data is None:
            return {}, {}

        images = await self._images(data)
        if len(images) == 1:
            images = images[0]

        result = {
            emojize(":orange_circle:"): (
                "This post contains more than 10 artworks. Open the post to find your image."
                if data.page_count > 10
                else None
            ),
            "Title": data.title,
            "Tags": tagify([(tag.translated_name or "") for tag in data.tags]),
            "Type": {"illust": "Artwork", "manga": "Manga", "ugoira": "GIF"}.get(data.type) or None,
            "Artworks in post": data.page_count,
            "Size": f"{data.width}x{data.height}",
            "Creator": data.user.name,
            "Creator [slug]": data.user.account,
            "18+ Audience": "Yes 🔞" if data.x_restrict else "No",
        }

        art_url = URL(f"https://www.pixiv.net/artworks/{illust_id}")

        meta: MetaData = {
            "provided_via": str(self.info["name"]),
            "provided_via_url": URL(str(self.info["url"])),
            "thumbnail": images,
            "buttons": [
                url_button(art_url, text="Source"),
                url_button(URL(f"https://www.pixiv.net/en/users/{data.user.id}"), text="Artist"),
            ],
            "identifier": str(art_url),
            "thumbnail_identifier": str(art_url),
        }

        return result, meta
