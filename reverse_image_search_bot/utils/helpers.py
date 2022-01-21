from pathlib import Path
import re
from threading import Thread
from typing import Any, BinaryIO

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


def get_file(name: str) -> Path:
    return Path(UPLOADER["configuration"]["path"]) / name


def get_file_from_url(url: str | URL):
    return get_file(str(url).replace(UPLOADER["url"].rstrip("/") + "/", ""))


def tagify(tags: list[str] | str) -> set[str]:
    if not tags:
        return set()
    tags = " ".join(map(lambda s: s.replace(" ", "_"), tags)) if isinstance(tags, list) else tags
    tags = re.sub(r"(?![_a-zA-Z0-9\s]).", "_", tags).split(" ")
    return {f"#{tag}".lower() for tag in filter(None, tags)}


class ReturnableThread(Thread):
    def __init__(self, target, args=(), kwargs={}):
        super().__init__(target=target, args=args, kwargs=kwargs)
        self._return = None

    def run(self):
        try:
            if self._target is not None:  # type: ignore
                self._return = self._target(*self._args, **self._kwargs)  # type: ignore
        finally:
            # Avoid a refcycle if the thread is running a function with
            # an argument that has a member that points to the thread.
            del self._target, self._args, self._kwargs  # type: ignore

    def join(self, timeout=None):
        super().join(timeout)
        return self._return


def safe_get(dct: dict | list, key_str: str, default: Any = None, none_to_default: bool = True) -> Any:
    """Safely get data from a multidimensional dict

    Examples:
        >>> data = {
        ...     "foo": "bar",
        ...     "hello": {
        ...         "world": "jeff",
        ...         "animal": [
        ...             {
        ...                 "type": "cat",
        ...                 "sound": "meow",
        ...                 "ja": "neko"
        ...             },
        ...             {
        ...                 "type": "shark",
        ...                 "sound": "a",
        ...                 "de": "hai"
        ...             }
        ...         ]
        ...     }
        ... }
        >>> safe_get(data, "foo")
        "bar"
        >>> safe_get(data, "hello.world")
        "jeff"
        >>> safe_get(data, "hello.animal[0]")
        {"type": "cat", "ja": "neko"}
        >>> safe_get(data, "hello.animal[type=cat]")
        {"type": "cat", "ja": "neko"}
        >>> safe_get(data, "hello.animal[type=shark].sound")
        "a"
        >>> safe_get(data, "hello.animal[de].type")
        "shark"
    """
    for key in key_str.split("."):
        try:
            if match := re.match(r"\[(\d+)\]", key):
                key = int(match.groups()[0])
            elif match := re.match(r"\[((?!=).+)=(.*)\]", key):
                if not isinstance(dct, list):
                    return default
                key, value = match.groups()
                if value.isdigit():
                    value = int(value)
                for dct in dct:
                    if dct[key] == value:  # type: ignore
                        break
                else:
                    return default
                continue
            elif match := re.match(r"\[(.*)\]", key):
                key = match.groups()[0]
                for dct in dct:
                    if key in dct:
                        break
                else:
                    return default
                continue
            dct = dct[key]  # type: ignore
        except (KeyError, IndexError, TypeError):
            return default
    return default if dct is None and none_to_default else dct
