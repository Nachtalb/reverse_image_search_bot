import random

from yarl import URL

from reverse_image_search_bot.engines.types import InternalProviderData, MetaData
from reverse_image_search_bot.utils import (
    danbooru_info,
    gelbooru_info,
    tagify,
    url_button,
)


class BooruProviders:
    def _danbooru_provider(self, danbooru_id: int) -> InternalProviderData:
        danbooru_data = danbooru_info(danbooru_id)
        if not danbooru_data:
            return {}, {}

        buttons = []
        if source := danbooru_data.get("source"):
            buttons.append(url_button(source, text="Source"))

        danbooru_url = URL(f"https://danbooru.donmai.us/posts/{danbooru_id}")
        buttons.append(url_button(danbooru_url))

        rating = {"s": "Safe", "q": "Questionable", "e": "Explicit"}.get(danbooru_data["rating"])

        result = {
            "Character": tagify(danbooru_data.get("tag_string_character", [])) or None,
            "Size": f"{danbooru_data['image_width']}x{danbooru_data['image_height']}",
            "Tags": tagify(random.choices(danbooru_data["tag_string_general"].split(" "), k=5)),
            "By": tagify(danbooru_data.get("tag_string_artist", [])) or None,
            "Copyright": danbooru_data.get("tag_string_copyright", None),
            "Rating": rating,
        }

        meta: MetaData = {
            "provided_via": "Danbooru",
            "provided_via_url": URL("https://danbooru.donmai.us/"),
            "thumbnail": URL(danbooru_data["large_file_url"]),  # type: ignore
            "buttons": buttons,
            "identifier": str(danbooru_url),
            "thumbnail_identifier": danbooru_data["large_file_url"],
        }

        return result, meta
