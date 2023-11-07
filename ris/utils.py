import re
from random import choices
from typing import Collection, Generator, Iterable, TypedDict

from yarl import URL


def chunks[T](lst: list[T], n: int) -> Generator[list[T], None, None]:  # type: ignore
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def tagify(tags: Iterable[str] | str) -> set[str]:
    """
    Convert a list of tags or a single tag (string) into a set of hashtag-like strings.

    If a tag starts with a digit, it is prefixed with an underscore.
    Non-alphanumeric characters (except for underscores) are replaced with underscores.
    The input can be either a single string or an iterable of strings.

    Args:
        tags (Iterable[str] | str): A single tag (string) or an iterable of tags (strings).

    Returns:
        set[str]: A set of hashtag-like strings.

    Examples:
        >>> tagify("(^.^)")
        set()

        >>> tagify("hello")
        {"#hello"}

        >>> tagify(["hello", "world"])
        {"#hello", "#world"}

        >>> tagify("123")
        {"#_123"}

        >>> tagify(["hello", "123"])
        {"#hello", "#_123"}
    """
    if not tags:
        return set()

    if isinstance(tags, str):
        tags = [tags]

    # Replace spaces with underscores and join the tags
    tags = " ".join(map(lambda s: s.replace(" ", "_"), tags))

    # Replace non-alphanumeric characters (except for underscores) with underscores
    tags = re.sub(r"\b_+\b", "", re.sub(r"(?![_a-zA-Z0-9\s]).", "_", tags)).split(" ")

    # Add a hashtag to each tag, and prefix tags starting with a digit with an underscore
    return {f"#_{tag}" if tag[0].isdigit() else f"#{tag}" for tag in filter(None, tags)}


def tagified_string(tags: Collection[str], limit: int = 0) -> str:
    """
    Create a string of hashtag-like strings from a list of tags.

    Args:
        tags (Sized[str]): An iterable of tags (strings).
        limit (int, optional): The maximum number of tags to include in the output string. Defaults to 0 (no limit).

    Returns:
        str: A string of hashtag-like strings separated by commas.

    Examples:
        >>> tagified_string(["hello", "world"])
        "#hello, #world"

        >>> tagified_string(["hello", "world"], limit=1)
        "#hello" or "#world"
    """
    if limit:
        tags = choices(list(tags), k=limit if limit < len(tags) else len(tags))
    return ", ".join(tagify(tags))


class Host(TypedDict):
    name: str
    emoji: str
    urls: list[str]


HOST_MAP: dict[str, Host] = {
    "twitter": {
        "name": "Twitter / X",
        "emoji": "🐦",
        "urls": ["twitter.com", "www.twitter.com", "pbs.twimg.com", "x.com"],
    },
    "artstation": {
        "name": "ArtStation",
        "emoji": "🎨",
        "urls": ["artstation.com", "www.artstation.com"],
    },
    "danbooru": {
        "name": "Danbooru",
        "emoji": "📦",
        "urls": ["danbooru.donmai.us"],
    },
    "pixiv": {
        "name": "Pixiv",
        "emoji": "🅿️",
        "urls": ["pixiv.net", "www.pixiv.net", "i.pximg.net"],
    },
    "deviantart": {
        "name": "DeviantArt",
        "emoji": "✏️",
        "urls": ["deviantart.com", "www.deviantart.com", "pre00.deviantart.net"],
    },
    "instagram": {
        "name": "Instagram",
        "emoji": "📷",
        "urls": ["instagram.com", "www.instagram.com", "scontent.cdninstagram.com"],
    },
    "tumblr": {
        "name": "Tumblr",
        "emoji": "💃",
        "urls": ["tumblr.com", "www.tumblr.com", "assets.tumblr.com"],
    },
    "yandere": {
        "name": "Yandere",
        "emoji": "✨",
        "urls": ["yande.re", "files.yande.re"],
    },
    "fanbox": {
        "name": "Fanbox",
        "emoji": "🅿️",
        "urls": ["fanbox.cc", "www.fanbox.ce"],
    },
    "mangadex": {
        "name": "MangaDex",
        "emoji": "📖",
        "urls": ["mangadex.org", "uploads.mangadex.org"],
    },
    "anime-planet": {
        "name": "Anime-Planet",
        "emoji": "🌎",
        "urls": ["anime-planet.com", "www.anime-planet.com"],
    },
    "kitsu": {
        "name": "Kitsu",
        "emoji": "🦊",
        "urls": ["kitsu.io", "media.kitsu.io"],
    },
    "mangaupdates": {
        "name": "MangaUpdates",
        "emoji": "📚",
        "urls": ["mangaupdates.com", "www.mangaupdates.com"],
    },
    "myanimelist": {
        "name": "MyAnimeList",
        "emoji": "📝",
        "urls": ["myanimelist.net", "cdn.myanimelist.net"],
    },
    "e621": {
        "name": "e621",
        "emoji": "🐕",
        "urls": ["e621.net", "static1.e621.net"],
    },
    "behoimi": {
        "name": "3dbooru",
        "emoji": "📷",
        "urls": ["behoimi.org"],
    },
    "3dbooru": {
        "name": "3dbooru",
        "emoji": "📷",
        "urls": ["behoimi.org"],
    },
}

URL_MAP = {url: key for key, data in HOST_MAP.items() for url in data["urls"]}

FALLBACK_EMOJIS = {
    "globe": "🌐",
    "picture": "🖼️",
}


def host_emoji(url: str | URL, fallback: str = FALLBACK_EMOJIS["picture"]) -> str:
    """
    Return a matching emoji for various art hosting sites.

    Args:
        url (str | URL): The URL of the art hosting site.
        fallback (str): The emoji to use as fallback if no host matched (default "🖼️")

    Returns:
        str: The matching emoji for the provided site.

    Examples:
        >>> host_emoji("https://twitter.com")
        '🐦'
        >>> host_emoji("https://artstation.com")
        '🎨'
        >>> host_emoji("https://pixiv.net")
        '🅿️'
    """
    url = URL(url)
    site_key = URL_MAP.get(url.host)  # type: ignore[arg-type]
    return HOST_MAP[site_key]["emoji"] if site_key else fallback


def host_name(url: str | URL, with_emoji: bool = True, fallback: str = FALLBACK_EMOJIS["picture"]) -> str:
    """
    Return a readable name for various art hosting sites with an optional emoji.

    Args:
        url (str | URL): The URL of the art hosting site.
        with_emoji (bool, optional): Include the emoji at the start of the name. Defaults to True.
        fallback (str): The emoji to use as fallback if no host matched (default "🖼️")

    Returns:
        str: The readable name of the provided site, with an optional emoji at the start.

    Examples:
        >>> host_name("https://twitter.com")
        'Twitter'
        >>> host_name("https://artstation.com", with_emoji=True)
        '🎨 ArtStation'
        >>> host_name("https://pixiv.net", with_emoji=True)
        '🅿️ Pixiv'
    """
    url = URL(url)
    site_key = URL_MAP.get(url.host)  # type: ignore[arg-type]

    if site_key:
        name = HOST_MAP[site_key]["name"]
        emoji = HOST_MAP[site_key]["emoji"] if with_emoji else fallback
    else:
        name = str(url.host if url.host else url)
        if name and name[:4] == "www.":
            name = name[4:]
        emoji = fallback

    return f"{emoji} {name}" if with_emoji else str(name)


def human_readable_volume(_bytes: float, right_alignment: int = 4, with_decimal: int = 0) -> str:
    """Return a human-readable representation of a number of bytes.

    Args:
        _bytes (float): The number of bytes.
        right_alignment (int): The number of characters to right-align the numbers to. Defaults to 4.
        with_decimal (int): The number of decimal places to include. Defaults to 0.

    Returns:
        str: A human-readable representation of the number of bytes.
    """
    if _bytes == 0:
        return f"{_bytes:>{right_alignment}.{with_decimal}f} B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while _bytes >= 1024 and i < len(units) - 1:
        _bytes /= 1024
        i += 1
    return f"{_bytes:>{right_alignment}.{with_decimal}f} {units[i]}"
