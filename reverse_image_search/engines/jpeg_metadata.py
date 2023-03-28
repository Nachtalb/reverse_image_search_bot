from pathlib import Path
from typing import Any

from PIL import ExifTags, Image
from telegram.ext import filters

from .metadata import MetadataEngine


class JpegMetadataEngine(MetadataEngine):
    name: str = "JPEG Metadata"
    description: str = "Retrieve metadata from JPEG files"
    supports: filters.BaseFilter = filters.PHOTO | filters.Document.JPG

    def get_metadata(self, file: Path) -> dict[str | int, Any]:
        data = {}
        with Image.open(file) as image:
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
