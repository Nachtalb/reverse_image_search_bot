from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import re

from emoji import emojize
from pixivpy3 import AppPixivAPI
from yarl import URL

from reverse_image_search_bot.config.pixiv_config import PixivConfig
from reverse_image_search_bot.engines.types import InternalProviderData, MetaData
from reverse_image_search_bot.utils import upload_file
from reverse_image_search_bot.utils import tagify, url_button

from .base import BaseProvider, provider_cache


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

    @provider_cache
    def request(self, illust_id: int | str):
        if isinstance(illust_id, str):
            if illust_id.isdigit():
                illust_id = int(illust_id)
            else:
                if reg_match := re.search(r"artworks\/(\d+)", illust_id):
                    illust_id = int(reg_match.groups()[0])
                else:
                    return
        data = self.api.illust_detail(illust_id)
        if data.error:
            self.logger.warning("Could not retrieve data: {data.error.user_message}")
            return
        return data.illust

    def _images(self, data) -> list[URL]:
        image_urls = []
        if 1 < data.page_count < 11:
            for image in data.meta_pages:
                image_urls.append(image.image_urls)
        else:
            image_urls.append(data.image_urls)

        images = []
        urls = []
        get_original = data.width + data.height < 10000
        for index, image in enumerate(image_urls):
            url = image.get("large", image.get("medium"))
            if get_original:
                url = image.get("original")
            urls.append((url, data.id, index))

        with ThreadPoolExecutor(max_workers=5) as executor:
            for image in executor.map(self._download_image, urls):
                if image:
                    images.append(image)

        return images

    def _download_image(self, url_data: tuple[str, int, int]) -> URL:
        url, post_id, index = url_data
        with BytesIO() as out:
            self.api.download(url, fname=out)
            return upload_file(out, file_name=f"{post_id}_p{index}{Path(url).name}")

    def provide(self, illust_id: int | str, page: int = None) -> InternalProviderData:
        if not self.authenticated:
            return {}, {}

        data = self.request(illust_id)
        if data is None:
            return {}, {}

        images = self._images(data)
        if len(images) == 1:
            images = images[0]

        result = {
            emojize(":orange_circle:"): (
                "This post contains more than 10 artworks, open the source to find your exact one"
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
            "provided_via": self.info["name"],
            "provided_via_url": URL(self.info["url"]),
            "thumbnail": images,
            "buttons": [
                url_button(art_url, text="Source"),
                url_button(URL(f"https://www.pixiv.net/en/users/{data.user.id}"), text="Artist"),
            ],
            "identifier": str(art_url),
            "thumbnail_identifier": str(art_url),
        }

        return result, meta
