from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from aiohttp import ClientSession
from telegram import InlineKeyboardButton
from telegram.ext import filters
from yarl import URL


@dataclass
class SearchResponse:
    engine: "SearchEngine"
    text: str
    buttons: list[InlineKeyboardButton] = field(default_factory=list)
    attachment: BinaryIO | None = None
    attachment_type: filters._Photo | filters._Video | None = None
    link: str | None = None


class SearchEngine:
    supports: filters.BaseFilter = filters.PHOTO
    name: str = "Search"
    description: str = "This is the base search engine"
    credits: str = "https://example.com"

    needs_webserver: bool = True  # Determines if the engine needs a webserver with public facing files
    supports_direct_search: bool = False  # If the engine can search for results on its own

    def __init__(self, session: ClientSession, credentials: dict[str, str] = {}) -> None:
        self.session = session
        self.credentials = credentials or {}

    async def search_photo(self, file: Path | URL) -> SearchResponse | None:
        raise NotImplemented

    async def search_video(self, file: Path | URL) -> SearchResponse | None:
        raise NotImplemented

    async def direct_search_photo(self, file: Path | URL) -> SearchResponse | None:
        raise NotImplemented

    async def direct_search_video(self, file: Path | URL) -> SearchResponse | None:
        raise NotImplemented
