import re
from asyncio import as_completed
from typing import AsyncGenerator, Coroutine

from aiohttp import ClientSession
from pydantic import BaseModel

from reverse_image_search.providers.base import Provider, SearchResult
from reverse_image_search.providers.booru import BooruQuery
from reverse_image_search.providers.pixiv import PixivQuery

from .base import SearchEngine


class SauceNaoSearchEngine(SearchEngine):
    """
    SauceNAO reverse image search engine implementation.

    Inherits from SearchEngine.

    Attributes:
        api_key (str): The API key for accessing the SauceNAO API.
        session (aiohttp.ClientSession): The aiohttp session for making requests.
        min_similarity (int): The minimum similarity a picture needs to count as match
        provider_mapping (dict[int, str]): Mapping between DB IDs and their provider methods,
                                           ordered by priority.
        providers (list[Formatter]): List of initialised data providers
    """

    name = "SauceNAO"
    description = (
        "SauceNAO is a reverse image search engine specializing in finding the source of anime, manga, and similar"
        " artwork. It has a large database and can provide accurate results for identifying the artists, sources, and"
        " related information for the images."
    )
    pros = ["Anime and manga focused", "Fast results"]
    cons = ["Limited to specific sources"]
    credit_url = "https://saucenao.com"
    query_url_template = "https://saucenao.com/search.php?url={file_url}"

    min_similarity = 65
    provider_mapping = {
        5: "_pixiv",
        9: "_booru",
        12: "_booru",
        25: "_booru",
        26: "_booru",
    }

    class Config(BaseModel):
        api_key: str

    def __init__(self, api_key: str, session: ClientSession, providers: dict[str, Provider]):
        """
        Initialise the SauceNaoSearchEngine.

        Args:
            api_key (str): The API key for accessing the SauceNAO API.
            session (aiohttp.ClientSession): The aiohttp session for making requests.
            providers (list[Formatter]): List of initialised data providers
        """
        super().__init__(providers)
        self.api_key = api_key
        self.session = session

    async def _api_search(self, file_url: str) -> dict:
        """
        Perform a search on the SauceNAO search engine using a file URL.

        Args:
            file_url (str): The URL of the image to search for.

        Returns:
            dict: A dictionary containing search results and related information.

        Raises:
            ValueError: If the file_url is not provided.

        Example:
            >>> async with aiohttp.ClientSession() as session:
                    sauce_nao = SauceNaoSearchEngine(api_key="your_api_key", session=session)
                    result = await sauce_nao.search("https://example.com/image.png")
                    print(result)
        """
        if not file_url:
            raise ValueError("file_url must be provided")

        query_url = self.query_url_template.format(file_url=file_url)
        headers = {"User-Agent": "reverse_image_search_bot/2.0"}

        async with self.session.get(
            query_url,
            headers=headers,
            params={"api_key": self.api_key, "output_type": 2},
        ) as response:
            return await response.json()

    async def search(self, file_url: str) -> AsyncGenerator[SearchResult, None]:
        results = await self._api_search(file_url)

        filtered_results = [
            result
            for result in results.get("results", [])
            if float(result["header"]["similarity"]) >= self.min_similarity
            and result["header"]["index_id"] in self.provider_mapping
        ]

        tasks: list[Coroutine[None, None, SearchResult | None]] = [
            getattr(self, self.provider_mapping[result["header"]["index_id"]])(result) for result in filtered_results
        ]

        for task in as_completed(tasks):
            if msg := await task:
                yield msg

    async def _booru(self, data: dict[str, dict[str, str | int | list[str]]]) -> SearchResult | None:
        if post_id := data["data"].get("danbooru_id"):
            return await self._safe_search(
                BooruQuery({"id": post_id, "provider": "danbooru"}),  # type: ignore[typeddict-item]
                "booru",
            )
        elif post_id := data["data"].get("yandere_id"):
            return await self._safe_search(
                BooruQuery({"id": post_id, "provider": "yandere"}),  # type: ignore[typeddict-item]
                "booru",
            )
        elif post_id := data["data"].get("gelbooru_id"):
            return await self._safe_search(
                BooruQuery({"id": post_id, "provider": "gelbooru_id"}),  # type: ignore[typeddict-item]
                "booru",
            )
        elif post_id := data["data"].get("konachan_id"):
            return await self._safe_search(
                BooruQuery({"id": post_id, "provider": "konachan"}),  # type: ignore[typeddict-item]
                "booru",
            )
        return None

    async def _pixiv(self, data: dict[str, dict[str, str | int | list[str]]]) -> SearchResult | None:
        query_data: PixivQuery = {
            "id": data["data"]["pixiv_id"],  # type: ignore[typeddict-item]
            "image_index": None,
        }

        if match := re.search(r"\d+_p(\d+)", str(data["header"]["index_name"])):
            query_data["image_index"] = int(match.groups()[0])

        return await self._safe_search(query_data, "pixiv")
