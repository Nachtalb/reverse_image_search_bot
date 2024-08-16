import logging
from typing import TYPE_CHECKING

from aiohttp import ClientSession

from .defaults import USER_AGENT
from .types import Info, Normalized, Provider, ProviderFunc, Source

if TYPE_CHECKING:
    from .distributor import Distributor

__all__ = ["PROVIDERS"]

log = logging.getLogger(__name__)


async def danbooru(engine_data: Normalized, session: ClientSession, distributor: "Distributor") -> Source | None:
    log_prefix = Provider.DANBOORU.value
    log.info(f"{log_prefix}: Getting source data")
    log.debug(f"{log_prefix}: Engine data: {engine_data}")
    log.debug(f"{log_prefix}: Distributor: {distributor}")
    id = engine_data["id"]
    url = f"https://danbooru.donmai.us/posts/{id}.json"

    log.debug(f"{log_prefix}: Getting data from {url}")
    async with session.get(url, headers={"User-Agent": USER_AGENT}) as response:
        response.raise_for_status()
        log.debug(f"{log_prefix}: Response status: {response.status}")
        data = await response.json()

    log.debug(f"{log_prefix}: Parsing data")
    authors = list(data.get("tag_string_artist", "").split(" "))
    characters = list(data.get("tag_string_character", "").split(" "))
    copyrights = list(data.get("tag_string_copyright", "").split(" "))
    tags = list(data.get("tag_string_general", "").split(" "))
    nsfw = data.get("rating", "") in ["e", "q"]

    danbooru_link = f"https://danbooru.donmai.us/posts/{id}"
    file_link = data.get("file_url")
    thumbnail_link = data.get("preview_file_url")
    source_link = data.get("source")

    link = (file_link, thumbnail_link)

    log.debug(f"{log_prefix}: Creating source")
    return Source(
        platform="danbooru",
        engine_data=engine_data,
        source_links=[link],
        additional_links=[danbooru_link, source_link],
        additional_info=[
            Info("Author", tags=authors, maxed=False),
            Info("Characters", tags=characters),
            Info("Tags", tags=tags),
            Info("Copyright", tags=copyrights),
            Info("NSFW", nsfw),
        ],
    )


async def pixiv(data: Normalized, session: ClientSession, distributor: "Distributor") -> Source | None:
    log_prefix = Provider.PIXIV.value
    log.info(f"{log_prefix}: Getting source data")
    log.debug(f"{log_prefix}: Engine data: {data}")
    log.debug(f"{log_prefix}: Distributor: {distributor}")
    log.warning(f"{log_prefix}: Not implemented")
    raise NotImplementedError


async def deviantart(data: Normalized, session: ClientSession, distributor: "Distributor") -> Source | None:
    log_prefix = Provider.DEVIANTART.value
    log.info(f"{log_prefix}: Getting source data")
    log.debug(f"{log_prefix}: Engine data: {data}")
    log.debug(f"{log_prefix}: Distributor: {distributor}")
    log.warning(f"{log_prefix}: Not implemented")
    raise NotImplementedError
    pass


async def saucenao_provider(data: Normalized, session: ClientSession, distributor: "Distributor") -> Source | None:
    log_prefix = Provider.SAUCENAO.value
    log.info(f"{log_prefix}: Getting source data")
    log.debug(f"{log_prefix}: Engine data: {data}")
    log.debug(f"{log_prefix}: Distributor: {distributor}")
    log.warning(f"{log_prefix}: Not implemented")
    raise NotImplementedError


PROVIDERS: dict[Provider, ProviderFunc] = {
    Provider.DANBOORU: danbooru,
    Provider.PIXIV: pixiv,
    Provider.DEVIANTART: deviantart,
    Provider.SAUCENAO: saucenao_provider,
}
