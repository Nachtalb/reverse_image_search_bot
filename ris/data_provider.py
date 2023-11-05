import json
from dataclasses import asdict, dataclass, field

from ris import common


@dataclass
class ProviderResult:
    provider_id: str  # In the form of "[provider_name]-[id]" (e.g. "danbooru-1234")
    provider_link: str  # Link to the page where the image was found
    main_file: list[str]  # Links to the most relevant file (e.g. the original image or a manga cover)

    fields: dict[str, str | list[str] | bool] = field(
        default_factory=dict
    )  # str == single value, list[str] == tags, bool == "Yes"/"No"
    extra_links: list[str] = field(default_factory=list)  # Links to other relevant pages

    def to_json(self) -> str:
        """Converts the object to a JSON string."""
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(json_str: str) -> "ProviderResult":
        """Converts a JSON string to a ProviderResult object."""
        return ProviderResult(**json.loads(json_str))


async def danbooru(id: str | int) -> ProviderResult | None:
    url = f"https://danbooru.donmai.us/posts/{id}.json"

    async with common.http_session.get(url) as response:
        data = await response.json()

    if not data:
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

    provider_id = f"danbooru-{id}"

    return ProviderResult(
        provider_link=link,
        main_file=file_link or thumbnail_link,
        fields={
            "authors": authors,
            "characters": characters,
            "tags": tags,
            "copyrights": copyrights,
            "nsfw": nsfw,
        },
        extra_links=[source_link],
        provider_id=provider_id,
    )


async def gelbooru(id: str | int) -> ProviderResult | None:
    url = f"https://gelbooru.com/index.php?page=dapi&s=post&q=index&json=1&id={id}"

    async with common.http_session.get(url) as response:
        data = await response.json()

    if not data or "post" not in data or not data["post"]:
        return None

    data = data["post"][0]

    tags = list(data.get("tags", "").split(" "))
    nsfw = data.get("rating", " ")[0] in ["e", "q"]

    link = f"https://gelbooru.com/index.php?page=post&s=view&id={id}"
    file_link = data.get("file_url")
    thumbnail_link = data.get("sample_url", data.get("preview_url"))
    source_link = data.get("source")

    provider_id = f"gelbooru-{id}"

    return ProviderResult(
        provider_link=link,
        main_file=file_link or thumbnail_link,
        fields={"tags": tags, "nsfw": nsfw},
        extra_links=[source_link],
        provider_id=provider_id,
    )


async def yandere(id: str | int) -> ProviderResult | None:
    url = f"https://yande.re/post.json?tags=id:{id}"

    async with common.http_session.get(url) as response:
        data = await response.json()

    if not data:
        return None

    data = data[0]

    tags = list(data.get("tags", "").split(" "))
    nsfw = data.get("rating", " ")[0] in ["e", "q"]

    link = f"https://yande.re/post/show/{id}"
    file_link = data.get("file_url", data.get("jpeg_url"))
    thumbnail_link = data.get("sample_url", data.get("preview_url"))
    source_link = data.get("source")

    provider_id = f"yandere-{id}"

    return ProviderResult(
        provider_link=link,
        main_file=file_link or thumbnail_link,
        fields={"tags": tags, "nsfw": nsfw},
        extra_links=[source_link],
        provider_id=provider_id,
    )


async def zerochan(id: str | int) -> ProviderResult | None:
    url = f"https://www.zerochan.net/{id}?json"

    async with common.http_session.get(url, headers={"User-Agent": common.LEGIT_USER_AGENT}) as response:
        data = await response.json(content_type=None)

    if not data:
        return None

    tags = data.get("tags", [])
    nsfw = False

    link = f"https://www.zerochan.net/{id}"
    file_link = data.get("full", data.get("large"))
    thumbnail_link = data.get("medium", data.get("small"))
    source_link = data.get("source")

    provider_id = f"zerochan-{id}"

    return ProviderResult(
        provider_link=link,
        main_file=file_link or thumbnail_link,
        fields={"tags": tags, "nsfw": nsfw},
        extra_links=[source_link],
        provider_id=provider_id,
    )
