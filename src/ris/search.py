import os
import re
from mimetypes import guess_extension
from typing import Any

import magic
from aiohttp import ClientResponseError, ClientSession, FormData

from .defaults import SAUCENAO_API_KEY, USER_AGENT
from .types import Engine, EngineFunc, Normalized, Normalizer, Provider

__all__ = ["ENGINES"]


snao_id_map = {
    "pixiv_id": Provider.PIXIV,
    "danbooru_id": Provider.DANBOORU,
    "gelbooru_id": Provider.GELBOORU,
    "mal_id": Provider.MYANIMELIST,
    "anidb_aid": Provider.ANIDB,
    "anilist_id": Provider.ANILIST,
    "da_id": Provider.DEVIANTART,
    "yandere_id": Provider.YANDERE,
}

snao_url_map = {
    Provider.EHENTAI: r"e-hentai\.org/?f_shash=(\w+)",
    Provider.PATREON: r"patreon\.com/posts/(\d+)",
}


def saucenao_normalisation(data: dict[str, Any], file_id: str) -> list[Normalized]:
    results = data["results"]
    normalized: list[Normalized] = []

    for result in results:
        rd = result["data"]
        hd = result["header"]

        # SIMPLE MAP
        for key, value in snao_id_map.items():
            if key in rd:
                normalized.append(
                    {
                        "platform": value,
                        "id": rd[key],
                        "engine": Engine.SAUCENAO,
                        "raw": result,
                        "similarity": float(hd["similarity"]),
                        "file_id": file_id,
                    }
                )

        # URL REGEX
        ext_urls = rd.get("ext_urls", [])
        for url in ext_urls:
            for platform, regex in snao_url_map.items():
                if match := re.match(regex, url):
                    normalized.append(
                        {
                            "platform": platform,
                            "id": match.group(1),
                            "engine": Engine.SAUCENAO,
                            "raw": result,
                            "similarity": float(hd["similarity"]),
                            "file_id": file_id,
                        }
                    )

    return normalized


async def saucenao(file_url: str, session: ClientSession) -> dict[str, Any]:
    params: dict[str, Any] = {"output_type": 2, "db": 999, "testmode": 1}
    if SAUCENAO_API_KEY:
        params["api_key"] = SAUCENAO_API_KEY

    url = "https://saucenao.com/search.php"

    if not os.path.exists(file_url):
        params["url"] = file_url

        async with session.get(url, headers={"User-Agent": USER_AGENT}, params=params) as response:
            response.raise_for_status()
            data = await response.json()
    else:
        mime = magic.Magic(mime=True)
        mime_type = mime.from_file(file_url)
        ext = guess_extension(mime_type)

        form_data = FormData()
        with open(file_url, "rb") as file:
            form_data.add_field("file", file, filename=f"image{ext}", content_type=mime_type)

            async with session.post(url, headers={"User-Agent": USER_AGENT}, data=form_data, params=params) as response:
                response.raise_for_status()
                data = await response.json()

    if (status_code := data.get("header", {}).get("status", None)) != 0:
        message = data.get("header", {}).get("message")
        if not message:
            message = "Unknown error"
            if status_code:
                message += f" (status code: {status_code})"

        raise ClientResponseError(
            response.request_info,
            (*response.history, response),
            status=response.status,
            message=message,
            headers=response.headers,
        )

    return data  # type: ignore[no-any-return]


ENGINES: dict[Engine, tuple[EngineFunc, Normalizer]] = {
    Engine.SAUCENAO: (saucenao, saucenao_normalisation),
}
