from abc import ABCMeta, abstractmethod
from asyncio import Lock
from time import time
from typing import Any, AsyncGenerator, TypedDict

from reverse_image_search.providers.base import Provider, QueryData, SearchResult


class CachedSearchResult(TypedDict):
    """
    CachedSearchResult represents a search result that has been cached.

    Attributes:
        found (int): The timestamp when the result was found.
        message (MessageConstruct | None): The message construct of the result, or None if not available.
    """

    found: int
    result: SearchResult | None


runtime_cache: dict[frozenset[tuple[str, Any]], CachedSearchResult] = {}


class SearchEngine(metaclass=ABCMeta):
    """
    Abstract base class for search engine implementations.

    Attributes:
        name (str): The name of the search engine.
        description (str): A brief description of the search engine.
        pros (list[str]): A list of the search engine's advantages.
        cons (list[str]): A list of the search engine's disadvantages.
        credit_url (str): The URL to the search engine's website.
        query_url_template (str): The template for generating search URLs.
        cache_time (int): Time to cache a search result in seconds (default 2 days).
        providers (dict[str, Provider], optional): A dict of data available providers (default empty dict)
        provider_lock (Lock): A threading lock used to prevent double search results.
    """

    name: str
    description: str
    pros: list[str]
    cons: list[str]
    credit_url: str
    query_url_template: str

    cache_time: int = 172800

    @abstractmethod
    def __init__(self, providers: dict[str, Provider] = {}):
        if not all(
            hasattr(self, attr) for attr in ("name", "description", "pros", "cons", "credit_url", "query_url_template")
        ):
            raise NotImplementedError("All required attributes must be provided by the subclass.")

        self.providers = providers
        self.provider_lock = Lock()

    def _get_cached(self, query: frozenset[tuple[str, Any]]) -> SearchResult | None | bool:
        """Get cached result for a given query.

        Fetches the cached result for a given query if it exists and is not expired.

        Args:
            query (Any): The query for which to fetch the cached result.

        Returns:
            SearchResult | None | bool: The cached result if it exists and is not expired, otherwise False.
        """
        if (result := runtime_cache.get(query)) and time() - result["found"] < self.cache_time:
            return result["result"]
        return False

    def _add_cached(self, query: frozenset[tuple[str, Any]], result: SearchResult | None = None) -> SearchResult | None:
        """Add a cached result for a given query.

        Stores the given message as the cached result for the specified query.

        Args:
            query (Any): The query for which to store the cached result.
            message (SearchResult | None, optional): The message to store as the cached result. Defaults to None.

        Returns:
            SearchResult | None: Returns the given message back
        """
        runtime_cache[query] = CachedSearchResult(found=int(time()), result=result)
        return result

    def generate_search_url(self, file_url: str) -> str:
        """
        Generate a search URL for the given file URL.

        Args:
            file_url (str): The URL of the file to be searched.

        Returns:
            str: The search URL generated using the query_url_template.
        """
        return self.query_url_template.format(file_url=file_url)

    async def _safe_search(self, query: QueryData, provider_name: str) -> SearchResult | None:
        """
        Perform a safe search by querying the provider in a locked context.

        Executes the search by querying the specified provider and stores the result in a cache
        while ensuring thread safety using a provider lock.

        Args:
            query (dict[str, Any]): The query to search for.
            provider_name (str): The name of the provider to use for the search.

        Returns:
            SearchResult | None: The search result if successful, otherwise None.
        """
        async with self.provider_lock:
            search_query = frozenset(query.items())
            if not isinstance((result := self._get_cached(search_query)), bool):
                return result
            self._add_cached(search_query)  # Reserve spot until provider is finished

        message = await self.providers[provider_name].provide(query)
        provider_info = self.providers[provider_name].provider_info(query)

        return self._add_cached(search_query, SearchResult(self, provider_info, message) if message else None)

    async def search(self, file_url: str) -> AsyncGenerator[SearchResult | None, None]:
        yield  # type: ignore
