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
