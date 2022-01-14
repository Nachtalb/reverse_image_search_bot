from pathlib import Path
from typing import BinaryIO

from yarl import URL

from reverse_image_search_bot.settings import UPLOADER
from reverse_image_search_bot.uploaders import uploader


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


def url_icon(url: URL | str, text_fallback: bool = False, with_text: bool = False) -> str:
    url = URL(url)

    match url.host:
        case "twitter.com":
            text = "Twitter"
            icon = "🐦"
        case "www.pixiv.net" | "pixiv.net":
            text = "Pixiv"
            icon = "🅿"
        case "danbooru.donmai.us":
            text = "Danbooru"
            icon = "📦"
        case _:
            text = url.host.split(".")[-2].title()  # type: ignore
            icon = "🌐"
            if text_fallback:
                icon = text
                text = ""

    if not with_text:
        text = ""
    return f"{icon} {text}"
