from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Callable, Coroutine, TypedDict, cast

from aiohttp import ClientSession

if TYPE_CHECKING:
    from .distributor import Distributor

Normalized = TypedDict(
    "Normalized",
    {
        "platform": "Provider",
        "id": str | int,
        "engine": "Engine",
        "raw": dict[str, Any],
        "similarity": float,  # 0 to 100
        "file_id": str,
    },
)
Errored = TypedDict(
    "Errored",
    {
        "error": str,
        "error_message": str,
        "error_data": Any,
        "error_type": str,
        "file": str,
        "engine": "Engine",
    },
)
InfoDict = TypedDict(
    "InfoDict",
    {
        "title": str,
        "description": str | int | float | None,
        "tags": list[str],
        "maxed": bool,
        "wrap_pre": bool,
        "wrap_code": bool,
        "url": str | None,
    },
)
SourceDict = TypedDict(
    "SourceDict",
    {
        "platform": "Provider",
        "engine_data": Normalized,
        "source_links": list[str | tuple[str, str]],
        "additional_links": list[str],
        "additional_info": list[InfoDict],
    },
)

EngineFunc = Callable[[str, ClientSession], Coroutine[Any, Any, dict[str, Any]]]
Normalizer = Callable[[Any, str], list[Normalized]]


@dataclass
class Info:
    title: str
    description: str | int | float | None = None
    tags: list[str] = field(default_factory=list)
    maxed: bool = True
    wrap_pre: bool = False
    wrap_code: bool = False
    url: str | None = None

    def dict(self) -> InfoDict:
        return cast(InfoDict, asdict(self))

    @classmethod
    def from_dict(cls, data: InfoDict) -> "Info":
        return cls(**data)


@dataclass
class Source:
    platform: str
    engine_data: Normalized
    source_links: list[str | tuple[str, str]]
    additional_links: list[str]
    additional_info: list[Info]

    def __post_init__(self) -> None:
        for info in self.additional_info[:]:
            if not info.tags and not info.description:
                self.additional_info.remove(info)

    def dict(self) -> SourceDict:
        return cast(SourceDict, asdict(self))

    @classmethod
    def from_dict(cls, data: SourceDict) -> "Source":
        data["additional_info"] = [Info.from_dict(info) for info in data["additional_info"]]  # type: ignore[misc]
        data["source_links"] = [tuple(link) if isinstance(link, list) else link for link in data["source_links"]]

        return cls(**data)  # type: ignore[arg-type]


ProviderFunc = Callable[[Normalized, ClientSession, "Distributor"], Coroutine[Any, Any, Source | None]]


class Provider(StrEnum):
    PIXIV = "pixiv"
    DANBOORU = "danbooru"
    GELBOORU = "gelbooru"
    MYANIMELIST = "myanimelist"
    ANIDB = "anidb"
    ANILIST = "anilist"
    DEVIANTART = "deviantart"
    SAUCENAO = "saucenao"
    YANDERE = "yandere"
    TWITTER = "twitter"
    EHENTAI = "ehentai"
    PATREON = "patreon"
    ARTSTATION = "artstation"
    COOMER = "coomer"


class Engine(StrEnum):
    SAUCENAO = "saucenao"
    IQDB = "iqdb"
    ASCII2D = "ascii2d"
    TRACE_MOE = "tracemoe"
    TINEYE = "tineye"
    GOOGLE = "google"
    YANDEX = "yandex"
    BING = "bing"
