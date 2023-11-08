import logging
import os
import re
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha1
from typing import Any, AsyncGenerator

from yarl import URL

from ris import common

SAUCENAO_API_KEY = os.environ["SAUCENAO_API_KEY"]
SAUCENAO_MIN_SIMILARITY = float(os.environ["SAUCENAO_MIN_SIMILARITY"])


@dataclass
class SearchResult:
    search_provider: str
    provider: str
    post_id: str | int
    similarity: float = -1.0
    extra_data: Any = None
    search_link: str | None = None

    @property
    def provider_id(self) -> str:
        if self.provider:
            return f"{self.provider}:{self.post_id}"
        return f"{self.search_provider}:{self.post_id}"


logger = logging.getLogger("ris.search_engines")


async def saucenao(image_url: str, image_id: str) -> AsyncGenerator[SearchResult, None]:
    """Search for image using saucenao.

    Args:
        image_url (str): Image url.
        image_id (str): Image id.

    Yields:
        AsyncGenerator[Result, None]: Async generator of results.
    """
    log_prefix = f"[{image_id}].saucenao:"
    logger.info(f"{log_prefix} starting search")
    url = f"https://saucenao.com/search.php?url={image_url}"

    params: dict[str, Any] = {"output_type": 2, "db": 999, "testmode": 1}
    if SAUCENAO_API_KEY:
        logger.debug(f"{log_prefix} using api key")
        params["api_key"] = SAUCENAO_API_KEY
    else:
        logger.debug(f"{log_prefix} not using api key")

    async with common.http_session.get(url, headers={"User-Agent": common.USER_AGENT}, params=params) as response:
        logger.debug(f"{log_prefix} got response")
        data = await response.json()

    # Known providers
    # provider id key: (saucenao index, provider name) | provider name
    ids: dict[str, str | tuple[int, str]] = {
        "danbooru_id": "danbooru",
        "yandere_id": "yandere",
        "gelbooru_id": "gelbooru",
        "konachan_id": "konachan",
        "sankaku_id": "sankaku",
        "pixiv_id": "pixiv",
        "md_id": "mangadex",
        "mu_id": "mangaupdates",
        "mal_id": "myanimelist",
        "da_id": "deviantart",
        "as_project": "artstation",
        "id": (43, "patreon"),
        "anidb_aid": "anidb",
        "anilist_id": "anilist",
        "tweet_id": "twitter",
        "imdb_id": "imdb",
        "e621_id": "e621",
    }

    for item in data.get("results", []):
        if float(item["header"]["similarity"]) < SAUCENAO_MIN_SIMILARITY:
            continue
        provider_found = False
        item["search_link"] = url
        for key, provider in ids.items():
            if key in item["data"]:
                if isinstance(provider, tuple):
                    if not provider[0] == item["header"]["index_id"]:
                        continue
                    logger.debug(
                        f"{log_prefix} found known provider result provider='{provider[1]}'"
                        f" {key=}='{item['data'][key]}'"
                    )
                    provider_found = True
                    yield SearchResult(
                        search_provider="saucenao",
                        provider=provider[1],
                        post_id=item["data"][key],
                        similarity=float(item["header"]["similarity"]),
                        extra_data=deepcopy(item),
                        search_link=url,
                    )
                else:
                    logger.debug(f"{log_prefix} found known provider result {provider=} {key=}='{item['data'][key]}'")
                    provider_found = True
                    yield SearchResult(
                        search_provider="saucenao",
                        provider=provider,
                        post_id=item["data"][key],
                        similarity=float(item["header"]["similarity"]),
                        extra_data=deepcopy(item),
                        search_link=url,
                    )
        if not provider_found:
            logger.debug(f"{log_prefix} found unknown provider result index='{item['header']['index_name']}'")
            yield SearchResult(
                search_provider="saucenao",
                provider="unknown",
                post_id=sha1(item["header"]["index_name"]).hexdigest(),
                similarity=float(item["header"]["similarity"]),
                extra_data=deepcopy(item),
                search_link=url,
            )
    logger.info(f"{log_prefix} finished search")


async def iqdb(image_url: str, image_id: str) -> AsyncGenerator[SearchResult, None]:
    """Search for image using iqdb.

    Specifically only search e-shuushuu (6), zerochan (11) and 3dbooru (7). The remaining providers
    are covered by saucenao which provides better results.

    Args:
        image_url (str): Image url.
        image_id (str): Image id.

    Yields:
        AsyncGenerator[Result, None]: Async generator of results.
    """
    log_prefix = f"[{image_id}].iqdb:"
    logger.info(f"{log_prefix} starting search")
    url = f"https://iqdb.org/?url={image_url}&service[]=6&service[]=11&service[]=7"

    async with common.http_session.get(url, headers={"User-Agent": common.LEGIT_USER_AGENT}) as response:
        logger.debug(f"{log_prefix} got response")
        html = await response.text()

    matches = re.findall(
        r'<div><table><tr><th>(?:Best match|Additional match)</th></tr><tr><td class=\'image\'><a href="([^"]+)"><img'
        r' src=\'([^"]+)\' alt="[^"]*" (?:title="[^"]*" )?width=\'\d+\' height=\'\d+\'></a></td>.*?(?:<td><img'
        r' alt="icon" src="/icon/[^.]+\.ico" class="service-icon">([^<]+)</td>)?.*?<td>(\d+×\d+)'
        r" \[([^\]]+)\]</td>.*?<td>(\d+)% similarity</td>",
        html,
        re.DOTALL,
    )

    if "Best match" in html and not matches:
        logger.debug(f"{log_prefix} 'Best match' found but no matches, regex broken?")

    provider_map: dict[str, str] = {
        "www.zerochan.net": "zerochan",
        "behoimi.org": "3dbooru",
        "e-shuushuu.net": "eshuushuu",
    }

    for match in matches:
        post_link = match[0].strip()
        data = {
            "provider": match[2].strip(),
            "post_link": post_link,
            "post_id": int(post_link.strip("/").split("/")[-1]),
            "thumbnail_src": match[1].strip(),
            "size": match[3].strip(),
            "nsfw": match[4].strip().lower() != "safe",
        }
        logger.debug(f"{log_prefix} found result provider='{data['provider']}'")
        similarity = float(match[5].strip())

        host = URL(post_link).host

        data["search_link"] = url

        yield SearchResult(
            search_provider="iqdb",
            provider=provider_map[host] if host in provider_map else (data["provider"] and "unknown"),
            post_id=data["post_id"],
            similarity=similarity,
            extra_data=data,
            search_link=url,
        )
    logger.info(f"{log_prefix} finished search")
