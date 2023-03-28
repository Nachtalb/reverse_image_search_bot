from pathlib import Path
from typing import Any

from telegram.ext import filters

from .metadata import MetadataEngine


class PngMetadataEngine(MetadataEngine):
    name: str = "PNG Metadata"
    description: str = "Retrieve metadata from PNG files"
    supports: filters.BaseFilter = filters.Document.MimeType("image/png")

    def get_metadata(self, file: Path) -> dict[str | int, Any]:
        data = {}
        return data
