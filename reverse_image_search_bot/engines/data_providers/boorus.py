from pathlib import Path
import random
import re
from tempfile import NamedTemporaryFile

from telegram import InlineKeyboardButton
from user_agent import generate_user_agent
import validators
from yarl import URL

from reverse_image_search_bot.engines.types import (
    InternalProviderData,
    InternalResultData,
    MetaData,
)
from reverse_image_search_bot.utils import tagify, upload_file, url_button
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
        "3dbooru": {
            "name": "3D Booru",
            "url": "http://behoimi.org/",
            "types": ["Cosplayers"],
            "site_type": "Imageboard",
        },
        "sankaku": {
            "name": "SankakuComplex",
            "url": "https://c1.sankakucomplex.com/",
            "types": ["Anime/Manga related Artworks"],
            "site_type": "Imageboard",
        },
    }

    urls = {
        "danbooru": {
            "check": "danbooru.donmai.us",
            "api_url": "https://danbooru.donmai.us/posts/{post_id}.json",
            "post_url": "https://danbooru.donmai.us/posts/{post_id}",
        },
        "gelbooru": {
            "check": "gelbooru.com",
            "id_reg": re.compile(r"id=(\d+)"),
            "api_url": "https://gelbooru.com/index.php?page=dapi&s=post&q=index&json=1&id={post_id}",
            "post_url": "https://gelbooru.com/index.php?page=post&s=view&id={post_id}",
        },
        "yandere": {
            "check": "yande.re",
            "api_url": "https://yande.re/post.json?tags=id:{post_id}",
            "post_url": "https://yande.re/post/show/{post_id}",
        },
        "3dbooru": {
            "check": "behoimi.org",
            "api_url": "http://behoimi.org/post/index.json?tags=id:{post_id}",
            "post_url": "http://behoimi.org/post/show/{post_id}",
            "download_thumbnail": True,
        },
        "sankaku": {
            "check": "chan.sankakucomplex.com",
            "api_url": "https://capi-v2.sankakucomplex.com/posts/{post_id}",
            "post_url": "https://chan.sankakucomplex.com/post/show/{post_id}",  # beta.sankakucomplex.com seems to have different post IDs
        },
    }

    def _request(self, api: str, post_id: int) -> dict | None:
        headers = {"User-Agent": generate_user_agent()}
        response = self.session.get(self.urls[api]["api_url"].format(post_id=post_id), headers=headers)
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
                if isinstance(data, list):
                    return next(iter(data), None)
                return data

    def source_button(self, data: dict) -> list[InlineKeyboardButton]:
        if (source := data.get("source")) and validators.url(source):
            return [url_button(source, text="Source")]
        return []

    def supports(self, url: URL | str) -> tuple[str, int] | tuple[None, None]:
        url = URL(url)
        api = next(filter(lambda service: self.urls[service]["check"] == url.host, self.urls), None)
        if not api:
            return None, None
        post_id = None
        if matcher := self.urls[api].get("id_reg"):
            if match := matcher.match(str(url)):
                post_id = match.groups()[0]
        else:
            post_id = url.parts[-1]

        if not api or not post_id or not post_id.isdigit():
            return None, None
        return api, int(post_id)

    def _get_thumbnail(self, api: str, post_id: int, data: dict) -> MetaData:
        thumbnail_url: str = data.get("file_url", data.get("sample_url", data.get("preview_file_url")))

        if not thumbnail_url:
            return {}
        elif self.urls[api].get("download_thumbnail"):
            headers = {
                "User-Agent": generate_user_agent(),
                "Referer": self.urls[api]["post_url"].format(post_id=post_id),
            }
            response = self.session.get(thumbnail_url, headers=headers)
            if response.status_code != 200:
                return {}

            with NamedTemporaryFile('rb+', delete=False) as file:
                file.write(response.content)
                file.seek(0)
                thumbnail = upload_file(Path(file.name), URL(thumbnail_url).name)
        else:
            thumbnail = URL(thumbnail_url)

        return {"thumbnail": thumbnail, "thumbnail_identifier": thumbnail_url}

    def _get_tags(self, data: dict) -> InternalResultData:
        main_tags = data.get('tag_string_general', data.get('tags', ''))
        if isinstance(main_tags, list):
            kinds = {
                0: 'general',
                1: 'artist',
                2: 'general',  # Don't know exactly what kind of tags belong here but it seems to include loli
                3: 'copyright',
                4: 'character',
                5: 'general',  # Seems to be parrent tag, eg. bdsm > (bondage, dominance, ..)
                8: 'meta',     # Meta information about the image not it's content directly, eg. high_resolution, large_filesize etc.
                9: 'general',  # Some kind of descriptive of the kind of action, eg. extreme content, contentious content

                # Haven't seen any 6 & 7 so I can't determine what they are
            }
            tags = {}
            for tag in main_tags:
                kind = kinds.get(tag['type'])
                if kind:
                    tags.setdefault(kind, [])
                    tags[kind].append(tag)

            chartags = set(tags.get('character', []))
            authortags = set(tags.get('artist', []))
            copyrighttags = set(tags.get('copyrighttags', []))
            main_tags = set(tags.get('general', []) + tags.get('meta', []))
        else:
            chartags = set(data.get('tag_string_character', '').split(' '))
            authortags = set(data.get('tag_string_artist', '').split(' '))
            copyrighttags = set(data.get('tag_string_copyright', '').split(' '))
            main_tags = set(main_tags.split(' ')) - copyrighttags - authortags - chartags

        return {
            'Character': tagify(chartags) or None,
            'Tags': tagify(random.choices(list(main_tags), k=5)) or None,
            'By': tagify(authortags) or None,
            'Copyright': copyrighttags or None,
        }

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
            'By': None,  # Placeholder to keep the order
            "Size": "{}x{}".format(
                data["image_width" if api == "danbooru" else "width"],
                data["image_height" if api == "danbooru" else "height"],
            ),
            "Rating": rating,
        }
        result.update(self._get_tags(data))

        meta: MetaData = {
            "provided_via": self.infos[api]["name"],
            "provided_via_url": URL(self.infos[api]["url"]),
            "buttons": buttons,
            "identifier": post_url,
        }

        if thumbnail_data := self._get_thumbnail(api, post_id, data):
            meta.update(thumbnail_data)

        return result, meta
