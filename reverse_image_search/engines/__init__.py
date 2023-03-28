from typing import Type

from .base import SearchEngine, SearchResponse
from .jpeg_metadata import JpegMetadataEngine
from .png_metadata import PngMetadataEngine
from .webp_metadata import WebpMetadataEngine

engines: list[Type[SearchEngine]] = [JpegMetadataEngine, PngMetadataEngine, WebpMetadataEngine]
