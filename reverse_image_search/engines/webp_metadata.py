from pathlib import Path
from typing import Any

from telegram.ext import filters

from .metadata import MetadataEngine


class WebpMetadataEngine(MetadataEngine):
    name: str = "WEBP Metadata"
    description: str = "Retrieve Metadata from WEBP files"
    supports: filters.BaseFilter = filters.Sticker.STATIC | filters.Document.MimeType("image/webp")

    def get_metadata(self, file: Path) -> dict[str | int, Any]:
        data = {}
        return data
