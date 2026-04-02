from __future__ import annotations

import asyncio
import io
import logging
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import time

from PIL import Image
from telegram import Animation, Document, PhotoSize, Sticker, Video
from yarl import URL

from reverse_image_search_bot.i18n import t
from reverse_image_search_bot.uploaders import uploader
from reverse_image_search_bot.utils import upload_file

logger = logging.getLogger(__name__)

last_used: dict[int, float] = {}

_process_executor = ProcessPoolExecutor(max_workers=2)

_LOCAL = Path(__file__).parent.parent
_HELP_IMAGE = _LOCAL / "images/help.jpg"

_LANG_NAMES: dict[str, str] = {
    "auto": "🌐 Auto",
    "en": "🇬🇧 English",
    "ru": "🇷🇺 Русский",
    "zh": "🇨🇳 中文",
    "es": "🇪🇸 Español",
    "it": "🇮🇹 Italiano",
    "ar": "🇸🇦 العربية",
    "ja": "🇯🇵 日本語",
    "de": "🇩🇪 Deutsch",
    "fr": "🇫🇷 Français",
    "pt": "🇧🇷 Português",
}

# Telegram Bot API file download limit (20 MB)
MAX_TELEGRAM_FILE_SIZE = 20 * 1024 * 1024


def _extract_video_frame(video_path: str) -> bytes:
    """Extract the first frame from a video as JPEG bytes. Runs in a separate process."""
    from moviepy.video.io.VideoFileClip import VideoFileClip
    from PIL import Image

    with VideoFileClip(video_path, audio=False) as clip:
        frame = clip.get_frame(0)
    buf = io.BytesIO()
    Image.fromarray(frame, "RGB").save(buf, "jpeg")
    return buf.getvalue()


def _detect_file_type(attachment) -> str:
    """Determine file type string from a Telegram attachment."""
    if isinstance(attachment, Sticker):
        return "sticker"
    elif isinstance(attachment, Animation):
        return "gif"
    elif isinstance(attachment, Video):
        return "video"
    elif isinstance(attachment, PhotoSize):
        return "photo"
    elif isinstance(attachment, Document):
        return "document"
    return "unknown"


# Mapping of file extensions to their normalized form
_EXTENSION_ALIASES: dict[str, str] = {
    "jpeg": "jpg",
    "jfif": "jpg",
    "jpe": "jpg",
    "tiff": "tif",
    "mpeg": "mpg",
}


def _normalize_extension(attachment) -> str:
    """Extract and normalize file extension from a Telegram attachment.

    Tries ``file_name`` first, then falls back to ``mime_type``.
    Returns a lowercase normalized extension (e.g. ``jpg``, ``png``, ``mp4``)
    or ``"unknown"`` when neither is available.
    """
    ext = None

    # Try file_name first (Documents, Videos, etc.)
    file_name = getattr(attachment, "file_name", None)
    if file_name and "." in file_name:
        ext = file_name.rsplit(".", 1)[-1].lower().strip()

    # Fall back to mime_type
    if not ext:
        mime = getattr(attachment, "mime_type", None)
        if mime and "/" in mime:
            ext = mime.split("/", 1)[-1].lower().strip()

    if not ext:
        # PhotoSize has no mime_type or file_name — it's always JPEG
        if isinstance(attachment, PhotoSize):
            return "jpg"
        return "unknown"

    return _EXTENSION_ALIASES.get(ext, ext)


_JPEG_ALIASES = {"jfif", "jpe", "jpeg"}


async def video_to_url(attachment: Document | Video | Animation | Sticker) -> URL:
    filename = f"{attachment.file_unique_id}.jpg"
    if uploader.file_exists(filename):
        return uploader.get_url(filename)

    if attachment.file_size and attachment.file_size > MAX_TELEGRAM_FILE_SIZE:
        if attachment.thumbnail:
            return await image_to_url(attachment.thumbnail)
        raise ValueError(t("search.files.video_too_large"))

    t0 = time()
    logger.info("video_to_url: downloading file %s", attachment.file_unique_id)
    video_file = await attachment.get_file()
    with NamedTemporaryFile(suffix=".mp4") as tmp:
        await video_file.download_to_drive(tmp.name)
        logger.info("video_to_url: downloaded in %.1fs, extracting frame", time() - t0)
        loop = asyncio.get_running_loop()
        frame_bytes = await loop.run_in_executor(_process_executor, _extract_video_frame, tmp.name)

    with io.BytesIO(frame_bytes) as file:
        url = upload_file(file, filename)
    logger.info("video_to_url: done in %.1fs -> %s", time() - t0, url)
    return url


async def image_to_url(attachment: PhotoSize | Sticker | Document) -> URL:
    if isinstance(attachment, Document):
        extension = (attachment.file_name or "unknown.jpg").lower().rsplit(".", 1)[1].strip(".")
        if extension in _JPEG_ALIASES:
            extension = "jpg"
    else:
        extension = "jpg" if isinstance(attachment, PhotoSize) else "png"

    filename = f"{attachment.file_unique_id}.{extension}"
    if uploader.file_exists(filename):
        return uploader.get_url(filename)

    t0 = time()
    logger.info("image_to_url: downloading file %s", attachment.file_unique_id)
    photo_file = await attachment.get_file()
    with io.BytesIO() as file:
        await photo_file.download_to_memory(file)
        logger.info("image_to_url: downloaded in %.1fs", time() - t0)
        if extension != "jpg":
            file.seek(0)
            with Image.open(file) as image:
                file.seek(0)
                image.save(file, extension)
        url = upload_file(file, filename)
    logger.info("image_to_url: done in %.1fs -> %s", time() - t0, url)
    return url
