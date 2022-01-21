import random

from telegram import InlineKeyboardButton
import validators
from yarl import URL

from reverse_image_search_bot.engines.types import InternalProviderData, MetaData
from reverse_image_search_bot.utils import tagify, url_button
from reverse_image_search_bot.utils.helpers import safe_get

from .base import BaseProvider, provider_cache


class BooruProvider(BaseProvider):
    infos = {
        "danbooru": {
            "name": "Danbooru",
            "url": "https://danbooru.donmai.us/",
            "types": ["Anime/Manage related Artworks"],
            "site_type": "Imageboard",
        },
        "gelbooru": {
            "name": "Gelbooru",
            "url": "https://gelbooru.com/",
            "types": ["Anime/Manage related Artworks"],
            "site_type": "Imageboard",
        },
        "yandere": {
            "name": "Yandere",
            "url": "https://yande.re/",
            "types": ["Anime/Manage related Artworks"],
            "site_type": "Imageboard",
        },
    }

    urls = {
        "danbooru": {
            "api_url": "https://danbooru.donmai.us/posts/{post_id}.json",
            "post_url": "https://danbooru.donmai.us/posts/{post_id}",
        },
        "gelbooru": {
            "api_url": "https://gelbooru.com/index.php?page=dapi&s=post&q=index&json=1&id={post_id}",
            "post_url": "https://gelbooru.com/index.php?page=post&s=view&id={post_id}",
        },
        "yandere": {
            "api_url": "https://yande.re/post.json?tags=id:{post_id}",
            "post_url": "https://yandere.com/index.php?page=post&s=view&id={post_id}",
        },
    }

    def _request(self, api: str, post_id: int) -> dict | None:
        response = self.session.get(self.urls[api]["api_url"].format(post_id=post_id))
        if response.status_code != 200:
            return
        return response.json()

    def get_post(self, api: str, post_id: int) -> dict | None:
        data = self._request(api, post_id)
        if not data:
            return
        match api:
            case "danbooru":
                if data.get("success") is not False:
                    return data
            case "gelbooru":
                if safe_get(data, "@attributes.count"):
                    return data["post"][0]
            case _:
                return data

    def source_button(self, data: dict) -> list[InlineKeyboardButton]:
        if (source := data.get("source")) and validators.url(source):
            return [url_button(source, text="Source")]
        return []

    def supports(self, url: URL | str) -> tuple[str, int] | tuple[None, None]:
        url = URL(url)
        api = {"danbooru.donmai.us": "danbooru", "yande.re": "yandere", "gelbooru.com": "gelbooru"}.get(url.host)  # type: ignore
        post_id = url.parts[-1] if url.parts and url.host != "gelbooru.com" else url.query.get("id")
        if not api or not post_id or not post_id.isdigit():
            return None, None
        return api, int(post_id)

    @provider_cache
    def provide(self, api_or_url: str | URL, post_id: int = None) -> InternalProviderData:
        if isinstance(api_or_url, URL) or validators.url(api_or_url):  # type: ignore
            api, post_id = self.supports(api_or_url)
        else:
            api = str(api_or_url)

        if api is None or not post_id:
            return {}, {}

        data = self.get_post(api, post_id)
        if not data:
            return {}, {}

        buttons = self.source_button(data)
        post_url = self.urls[api]["post_url"].format(post_id=post_id)
        buttons.append(url_button(post_url))

        rating = data["rating"].title()
        if api != "gelbooru":
            rating = {"S": "Safe", "Q": "Questionable", "E": "Explicit"}.get(rating)

        result = {
            "Title": data.get("Title"),
            "Character": tagify(data.get("tag_string_character", [])) or None,
            "Size": "{}x{}".format(
                data["image_width" if api == "danbooru" else "width"],
                data["image_height" if api == "danbooru" else "height"],
            ),
            "Tags": tagify(random.choices(data["tag_string_general" if api == "danbooru" else "tags"].split(" "), k=5)),
            "By": tagify(data.get("tag_string_artist", [])) or None,
            "Copyright": data.get("tag_string_copyright", "").split(" "),
            "Rating": rating,
        }

        meta: MetaData = {
            "provided_via": self.infos[api]["name"],
            "provided_via_url": URL(self.infos[api]["url"]),
            "thumbnail": data["file_url"],
            "buttons": buttons,
            "identifier": post_url,
            "thumbnail_identifier": data["file_url"],
        }
        return result, meta
