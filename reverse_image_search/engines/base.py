from abc import ABCMeta, abstractmethod
from typing import AsyncGenerator

from reverse_image_search.providers.base import MessageConstruct


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
    """

    name: str
    description: str
    pros: list[str]
    cons: list[str]
    credit_url: str
    query_url_template: str

    @abstractmethod
    def __init__(self):
        if not all(
            hasattr(self, attr) for attr in ("name", "description", "pros", "cons", "credit_url", "query_url_template")
        ):
            raise NotImplementedError("All required attributes must be provided by the subclass.")

    def generate_search_url(self, file_url: str) -> str:
        """
        Generate a search URL for the given file URL.

        Args:
            file_url (str): The URL of the file to be searched.

        Returns:
            str: The search URL generated using the query_url_template.
        """
        return self.query_url_template.format(file_url=file_url)

    async def search(self, file_url: str) -> AsyncGenerator[MessageConstruct | None, None]:
        yield
