import json
from pathlib import Path
import re
from typing import BinaryIO

from cachetools import TTLCache, cached
from requests import Session
from telegram import InlineKeyboardButton
from yarl import URL

from reverse_image_search_bot.settings import UPLOADER
from reverse_image_search_bot.uploaders import uploader

DataAPICache = TTLCache(maxsize=1e4, ttl=12 * 60 * 60)


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def upload_file(file: Path | BinaryIO, file_name: str) -> URL:
    """Upload the given image to the in the settings specified place.

    Args:
        image_file: File like object of an image or path to an image
        file_name (:obj:`str`): Name of the given file. Can be left empty if image_file is a file path
    Returns:
        :obj:`URL`: URL to the uploaded file
    """
    with uploader:
        uploader.upload(file, file_name)

    return URL(UPLOADER["url"]) / file_name


def fix_url(url: URL | str) -> URL:
    url = URL(url)

    match url.host:
        case "i.pximg.net":
            art_id_match = re.match(r"^\d+", next(reversed(url.parts)))
            if art_id_match:
                art_id = art_id_match[0]
                return URL("https://www.pixiv.net/artworks/" + art_id)

    return url


def url_icon(url: URL | str, with_icon: bool = True, with_text: bool = True) -> str:
    url = URL(url)

    match url.host:
        case "twitter.com":
            text = "Twitter"
            icon = "🐦"
        case "www.pixiv.net" | "pixiv.net" | "i.pximg.net":
            text = "Pixiv"
            icon = "🅿"
        case "danbooru.donmai.us":
            text = "Danbooru"
            icon = "📦"
        case _:
            text = url.host.split(".")[-2].title()  # type: ignore
            icon = "🌐"

    if not with_text:
        text = ""
    if not with_icon:
        text = ""
    return f"{icon} {text}"


def url_button(
    url: URL | str, with_icon: bool = True, with_text: bool = True, fix_url_: bool = True
) -> InlineKeyboardButton:
    if fix_url_:
        url = fix_url(url)
    return InlineKeyboardButton(text=url_icon(url, with_icon, with_text), url=str(url))


def tagify(tags: list[str] | str) -> list[str]:
    if not tags:
        return []
    tags = " ".join(map(lambda s: s.replace(" ", "_"), tags)) if isinstance(tags, list) else tags
    tags = re.sub(r"(?![_a-zA-Z0-9\s]).", "_", tags).split(" ")
    return [f"#{tag}" for tag in filter(None, tags)]


ANILIST_SESSION = Session()


@cached(DataAPICache)
def anilist_info(anilist_id: int) -> dict | None:
    query = """
query ($id: Int) {
    Page (perPage: 1) {
        media (id: $id) {
            title {
                english
                romaji
            }
            coverImage {
                large
            }
            startDate {
                year
            }
            endDate {
                year
            }
            episodes
            status
            siteUrl
            type
            genres
        }
    }
}
    """.strip()

    payload = json.dumps({"query": query, "variables": {"id": anilist_id}})

    response = ANILIST_SESSION.post(
        "https://graphql.anilist.co", data=payload, headers={"Content-Type": "application/json"}
    )
    if response.status_code != 200:
        return

    return next(iter(response.json()["data"]["Page"]["media"]), None)


DANBOORU_SESSION = Session()


@cached(DataAPICache)
def danbooru_info(danbooru_id: int) -> dict | None:
    response = DANBOORU_SESSION.get(
        f"https://danbooru.donmai.us/posts/{danbooru_id}.json", headers={"Content-Type": "application/json"}
    )

    if response.status_code != 200 or response.json().get("success") is False:
        return

    return response.json()
