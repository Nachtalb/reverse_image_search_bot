from typing import Type

from .base import SearchEngine, SearchResponse
from .metadata import JpegMetadataEngine

engines: list[Type[SearchEngine]] = [JpegMetadataEngine]
