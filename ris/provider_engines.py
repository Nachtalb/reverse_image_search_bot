import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from yarl import URL

from ris import common

logger = logging.getLogger("ris.provider_engines")


@dataclass
class ProviderData:
    priority_key: str  # The key used to sort the results
    provider_id: (
        str  # In the form of "[provider_name]:[id]" [search_engine]:[provider_name]:[id] (e.g. "danbooru:1234" )
    )
    provider_link: str  # Link to the page where the image was found
    main_files: list[str]  # Links to the most relevant file (e.g. the original image or a manga cover)

    fields: dict[str, str | list[str] | bool] = field(
        default_factory=dict
    )  # str == single value, list[str] == tags, bool == "Yes"/"No"
    extra_links: set[str] = field(default_factory=set)  # Links to other relevant pages

    def to_json(self) -> str:
        """Converts the object to a JSON string."""
        data = asdict(self)
        data["extra_links"] = list(data["extra_links"])

        return json.dumps(data)

    @staticmethod
    def from_json(json_str: str) -> "ProviderData":
        """Converts a JSON string to a ProviderResult object."""
        data = json.loads(json_str)
        data["extra_links"] = set(data["extra_links"])

        return ProviderData(**data)


async def saucenao_generic(provider_name: str, id: str, extra_data: Any) -> ProviderData | None:
    """Process unknown saucenao result."""
    log_prefix = f"[{id}].saucenao_generic:"
    logger.debug(f"{log_prefix} processing result from generic result")
    extra_links = set(extra_data["data"].pop("ext_urls", []))

    fields = extra_data["data"]
    for key, value in list(fields.items()):
        if value is None or value in ["None", "", "null", ["unknown"]]:
            fields.pop(key)
        try:
            if URL(value).host:
                extra_links.add(fields.pop(key))
        except TypeError:
            pass

    provider_id = (
        f"saucenao:{id}" if not provider_name or provider_name == "unknown" else f"saucenao:{provider_name}:{id}"
    )
    return ProviderData(
        priority_key=provider_name if provider_name and provider_name != "unknown" else id,
        provider_id=provider_id,
        main_files=[extra_data["header"]["thumbnail"]],
        provider_link=extra_data["search_link"],
        fields=extra_data["data"],
        extra_links=extra_links,
    )


def _saucenao_extra_links(data: dict[str, Any]) -> set[str]:
    """Get extra links from saucenao data."""
    if not isinstance(data, dict):
        return []
    extra_links = set()
    if "search_link" in data:
        extra_links.add(data["search_link"])

    for key, value in data.get("data", {}).items():
        if key == "ext_urls" and isinstance(value, list):
            extra_links |= set(value)
        try:
            if URL(value).host:
                extra_links.add(value)
        except TypeError:
            pass
    for value in extra_links.copy():
        if "danbooru.donmai.us" in value and "post/show/" in value:
            extra_links.remove(value)
            extra_links.add(value.replace("post/show", "posts"))
    return extra_links


async def iqdb_generic(provider_name: str, id: str, extra_data: Any) -> ProviderData | None:
    """Process generic iqdb result."""
    log_prefix = f"[{id}].iqdb_generic:"
    logger.debug(f"{log_prefix} processing result from generic result")

    provider_id = f"iqdb:{id}" if not provider_name or provider_name == "unknown" else f"iqdb:{provider_name}:{id}"
    return ProviderData(
        priority_key=provider_name if provider_name and provider_name != "unknown" else id,
        provider_id=provider_id,
        main_files=[extra_data["thumbnail_sec"]],
        provider_link=extra_data["post_link"],
        fields={
            "size": extra_data["size"],
            "nsfw": extra_data["nsfw"],
        },
    )


async def danbooru(id: str | int, extra_data: Any) -> ProviderData | None:
    log_prefix = f"[{id}].danbooru:"
    logger.debug(f"{log_prefix} fetching post")

    url = f"https://danbooru.donmai.us/posts/{id}.json"

    async with common.http_session.get(url) as response:
        logger.debug(f"{log_prefix} got response")
        data = await response.json()

    if not data:
        logger.debug(f"{log_prefix} no data")
        return None

    authors = list(data.get("tag_string_artist", "").split(" "))
    characters = list(data.get("tag_string_character", "").split(" "))
    copyrights = list(data.get("tag_string_copyright", "").split(" "))
    tags = list(data.get("tag_string_general", "").split(" "))
    nsfw = data.get("rating", "") in ["e", "q"]

    link = f"https://danbooru.donmai.us/posts/{id}"
    file_link = data.get("file_url")
    thumbnail_link = data.get("preview_file_url")
    source_link = data.get("source")

    provider_id = f"danbooru:{id}"

    return ProviderData(
        priority_key="danbooru",
        provider_link=link,
        main_files=[file_link or thumbnail_link],
        fields={
            "authors": authors,
            "characters": characters,
            "tags": tags,
            "copyrights": copyrights,
            "nsfw": nsfw,
        },
        extra_links={source_link} | _saucenao_extra_links(extra_data),
        provider_id=provider_id,
    )


async def gelbooru(id: str | int, extra_data: Any) -> ProviderData | None:
    log_prefix = f"[{id}].gelbooru:"
    logger.debug(f"{log_prefix} fetching post")
    url = f"https://gelbooru.com/index.php?page=dapi&s=post&q=index&json=1&id={id}"

    async with common.http_session.get(url) as response:
        logger.debug(f"{log_prefix} got response")
        data = await response.json()

    if not data or "post" not in data or not data["post"]:
        logger.debug(f"{log_prefix} no data")
        return None

    data = data["post"][0]

    tags = list(data.get("tags", "").split(" "))
    nsfw = data.get("rating", " ")[0] in ["e", "q"]

    link = f"https://gelbooru.com/index.php?page=post&s=view&id={id}"
    file_link = data.get("file_url")
    thumbnail_link = data.get("sample_url", data.get("preview_url"))
    source_link = data.get("source")

    provider_id = f"gelbooru:{id}"

    return ProviderData(
        priority_key="gelbooru",
        provider_link=link,
        main_files=[file_link or thumbnail_link],
        fields={"tags": tags, "nsfw": nsfw},
        extra_links={source_link} | _saucenao_extra_links(extra_data),
        provider_id=provider_id,
    )


async def yandere(id: str | int, extra_data: Any) -> ProviderData | None:
    log_prefix = f"[{id}].yandere:"
    logger.debug(f"{log_prefix} fetching post")
    url = f"https://yande.re/post.json?tags=id:{id}"

    async with common.http_session.get(url) as response:
        logger.debug(f"{log_prefix} got response")
        data = await response.json()

    if not data:
        logger.debug(f"{log_prefix} no data")
        return None

    data = data[0]

    tags = list(data.get("tags", "").split(" "))
    nsfw = data.get("rating", " ")[0] in ["e", "q"]

    link = f"https://yande.re/post/show/{id}"
    file_link = data.get("file_url", data.get("jpeg_url"))
    thumbnail_link = data.get("sample_url", data.get("preview_url"))
    source_link = data.get("source")

    provider_id = f"yandere:{id}"

    return ProviderData(
        priority_key="yandere",
        provider_link=link,
        main_files=[file_link or thumbnail_link],
        fields={"tags": tags, "nsfw": nsfw},
        extra_links={source_link} | _saucenao_extra_links(extra_data),
        provider_id=provider_id,
    )


async def zerochan(id: str | int, extra_data: Any) -> ProviderData | None:
    log_prefix = f"[{id}].zerochan:"
    logger.debug(f"{log_prefix} fetching post")
    url = f"https://www.zerochan.net/{id}?json"

    async with common.http_session.get(url, headers={"User-Agent": common.LEGIT_USER_AGENT}) as response:
        logger.debug(f"{log_prefix} got response")
        data = await response.json(content_type=None)

    if not data:
        logger.debug(f"{log_prefix} no data")
        return None

    tags = data.get("tags", [])
    nsfw = False

    link = f"https://www.zerochan.net/{id}"
    file_link = data.get("full", data.get("large"))
    thumbnail_link = data.get("medium", data.get("small"))
    source_link = data.get("source")

    provider_id = f"zerochan:{id}"

    return ProviderData(
        priority_key="zerochan",
        provider_link=link,
        main_files=[file_link or thumbnail_link],
        fields={"tags": tags, "nsfw": nsfw},
        extra_links={source_link} | _saucenao_extra_links(extra_data),
        provider_id=provider_id,
    )


async def threedbooru(id: str | int, extra_data: Any) -> ProviderData | None:
    log_prefix = f"[{id}].threedbooru:"
    logger.debug(f"{log_prefix} fetching post")
    url = f"http://behoimi.org/post/index.json?tags=id:{id}"

    async with common.http_session.get(url, headers={"User-Agent": common.LEGIT_USER_AGENT}) as response:
        logger.debug(f"{log_prefix} got response")
        data = await response.json()

    if not data or not data[0]:
        logger.debug(f"{log_prefix} no data")
        return None

    tags = list(data[0].get("tags", "").split(" "))
    nsfw = data[0].get("rating", " ")[0] in ["e", "q"]

    link = f"http://behoimi.org/post/show/{id}"
    file_link = data[0].get(
        "preview_url"
    )  # The file_url and sample_url return placeholder images against crawlers etc.
    source = data[0].get("source")

    provider_id = f"3dbooru:{id}"

    return ProviderData(
        priority_key="3dbooru",
        provider_link=link,
        main_files=[file_link],
        fields={"tags": tags, "nsfw": nsfw},
        extra_links={source} | _saucenao_extra_links(extra_data),
        provider_id=provider_id,
    )


async def eshuushuu(id: str | int, extra_data: Any) -> ProviderData | None:
    log_prefix = f"[{id}].eshuushuu:"
    logger.debug(f"{log_prefix} fetching post")
    url = f"https://e-shuushuu.net/image/{id}/"

    async with common.http_session.get(url, headers={"User-Agent": common.LEGIT_USER_AGENT}) as response:
        logger.debug(f"{log_prefix} got response")
        html = await response.text()

    if not html:
        logger.debug(f"{log_prefix} no data")
        return None

    full_res_image_re = re.search(r'<a class="thumb_image" href="([^"]+)"', html)
    full_res_image: str = full_res_image_re.group(1) if full_res_image_re else ""
    if full_res_image:
        full_res_image = f"https://e-shuushuu.net{full_res_image}"
    else:
        logger.debug(f"{log_prefix} no full res image, regex broken?")
        return None

    tags_reg: str = r'<span class=\'tag\'>"<a href="/tags/\d+">([^<]+)</a>"</span>'

    tags_re = re.findall(tags_reg, html)
    source_re = re.search(r"Source:\s*</dt>\s*<dd[^>]*>\s*" + tags_reg, html)
    character_re = re.search(r"Characters:\s*</dt>\s*<dd[^>]*>\s*" + tags_reg, html)
    artist_re = re.search(r"Artist:\s*</dt>\s*<dd[^>]*>\s*" + tags_reg, html)

    tags = set(tags_re if tags_re else [])
    source = source_re.group(1) if source_re else ""
    character = character_re.group(1) if character_re else ""
    artist = artist_re.group(1) if artist_re else ""

    tags -= {source, character, artist}

    if not tags:
        logger.debug(f"{log_prefix} no tags, regex broken?")

    return ProviderData(
        priority_key="eshuushuu",
        provider_link=url,
        main_files=[full_res_image],
        fields={
            "tags": list(tags),
            "copyrights": [source],
            "character": character,
        },
        extra_links=_saucenao_extra_links(extra_data),
        provider_id=f"e_shuushuu:{id}",
    )
