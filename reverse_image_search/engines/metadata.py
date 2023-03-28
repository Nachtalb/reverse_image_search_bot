from pathlib import Path
from typing import Any

from PIL import ExifTags, Image
from telegram import MessageEntity
from telegram.ext import filters
from telegram.helpers import escape_markdown

from .base import SearchEngine, SearchResponse


class JpegMetadataEngine(SearchEngine):
    name: str = "Metadata"
    description: str = "Retrieve Metadata from a given file"
    credits: str = ""
    supports: filters.BaseFilter = filters.PHOTO | filters.Document.JPG

    needs_webserver: bool = False
    supports_direct_search: bool = True

    async def direct_search_photo(self, file: Path) -> SearchResponse | None:
        with Image.open(file) as image:
            exif_data = self.get_jpeg_metadata(image)

        parts = []
        for name, value in exif_data.items():
            value = escape_markdown(f'"{value}"' if isinstance(value, str) else str(value), 2, MessageEntity.CODE)
            parts.append(f"{name}: `{value}`")

        return SearchResponse(self, "\n".join(parts))

    def get_jpeg_metadata(self, image: Image.Image) -> dict[str | int, Any]:
        data = {}
        exif = image.getexif()
        if exif:
            # Basic exif (camera make/model, etc)
            for key, val in exif.items():
                if isinstance(val, bytes):
                    continue
                data[ExifTags.TAGS[key]] = val

            # Aperture, shutter, flash, lens, tz offset, etc
            ifd = exif.get_ifd(ExifTags.IFD.Exif)
            for key, val in ifd.items():
                if isinstance(val, bytes):
                    continue
                data[ExifTags.TAGS[key]] = val

            # GPS Info
            ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
            for key, val in ifd.items():
                if isinstance(val, bytes):
                    continue
                data[ExifTags.GPSTAGS[key]] = val

        return data
