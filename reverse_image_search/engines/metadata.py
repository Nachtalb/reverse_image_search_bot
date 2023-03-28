from abc import abstractmethod
from pathlib import Path
from typing import Any

from telegram import MessageEntity
from telegram.ext import filters
from telegram.helpers import escape_markdown

from .base import SearchEngine, SearchResponse


class MetadataEngine(SearchEngine):
    name: str = "Metadata"
    description: str = "Retrieve metadata from a given file"
    credits: str = ""
    supports: filters.BaseFilter = filters.Document.ALL

    needs_webserver: bool = False
    supports_direct_search: bool = True

    async def direct_search_photo(self, file: Path) -> SearchResponse | None:
        parts = []
        for name, value in self.get_metadata(file).items():
            value = escape_markdown(f'"{value}"' if isinstance(value, str) else str(value), 2, MessageEntity.CODE)
            parts.append(f"{name}: `{value}`")

        if not parts:
            return

        return SearchResponse(self, "\n".join(parts))

    @abstractmethod
    def get_metadata(self, file: Path) -> dict[str | int, Any]:
        ...
