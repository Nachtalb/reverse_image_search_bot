import os
from mimetypes import guess_extension
from typing import Any

import magic
from aiohttp import ClientResponseError, ClientSession, FormData

from .defaults import SAUCENAO_API_KEY, USER_AGENT
from .types import ENGINE

__all__ = ["engines"]


async def saucenao(file_url: str, session: ClientSession) -> dict[str, Any]:
    params: dict[str, Any] = {"output_type": 2, "db": 999, "testmode": 1}
    if SAUCENAO_API_KEY:
        params["api_key"] = SAUCENAO_API_KEY

    url = "https://saucenao.com/search.php"

    if not os.path.exists(file_url):
        params["url"] = file_url

        async with session.get(url, headers={"User-Agent": USER_AGENT}, params=params) as response:
            response.raise_for_status()
            print(response.status)
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
                print(response.status)
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


engines: dict[str, ENGINE] = {
    "saucenao": saucenao,
}
