from __future__ import annotations

import asyncio
import io
import logging
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import time

import httpx
import imageio_ffmpeg
from PIL import Image
from telegram import Animation, Document, PhotoSize, Sticker, Video
from yarl import URL

from reverse_image_search_bot.i18n import t
from reverse_image_search_bot.uploaders import uploader
from reverse_image_search_bot.utils import upload_file

logger = logging.getLogger(__name__)

last_used: dict[int, float] = {}

# ffmpeg binary (bundled via imageio-ffmpeg on glibc). Resolved once.
_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# Shared client for streaming video downloads off Telegram's file server.
# No read timeout — large files stream progressively; we stop them ourselves.
_dl_client = httpx.AsyncClient(timeout=httpx.Timeout(_FILE_TIMEOUT := 10.0, read=None))

# JPEG magic — a valid extracted frame starts with these three bytes.
_JPEG_MAGIC = b"\xff\xd8\xff"

# Download in 64 KiB chunks off Telegram's file server.
_DL_CHUNK = 64 * 1024

# Buffer thresholds at which to attempt an early decode (complete-prefix + EOF).
# Doubling keeps the number of ffmpeg spawns logarithmic in file size; streamable
# mp4/webm/mkv decode by ~1 MiB, so most uploads stop after 3 tries at ~6-7%.
_TRY_AT_BYTES = [256 * 1024, 512 * 1024, 1024 * 1024, 2 * 1024**2, 4 * 1024**2, 8 * 1024**2, 16 * 1024**2]

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


def _extract_frame_from_file(video_path: str) -> bytes:
    """Extract frame 0 from a seekable local file as JPEG bytes (fallback path).

    Used only when progressive streaming can't decode the file — i.e. an mp4
    with its moov atom at the end, which a non-seekable pipe cannot handle.
    """
    proc = subprocess.run(
        [
            _FFMPEG,
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-c:v",
            "mjpeg",
            # Near-lossless JPEG (1=best). ffmpeg's mjpeg default (~q5) is
            # visibly lossier than the old PIL q75 encode — search engines
            # deserve the best frame we can give them.
            "-q:v",
            "2",
            "-",
        ],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        detail = proc.stderr.decode("utf-8", "replace")[:500]
        raise RuntimeError(f"ffmpeg frame extraction failed (rc={proc.returncode}): {detail}")
    return proc.stdout


async def _try_decode_prefix(data: bytes) -> bytes | None:
    """Feed a complete byte prefix + EOF to a fresh ffmpeg and return the JPEG,
    or None if these bytes aren't enough to decode frame 0 yet.

    Complete-prefix-plus-EOF is the trick: it forces ffmpeg to decode from
    exactly `data` instead of greedily reading ahead on an open pipe (which
    pulled 75% of the file). Streamable mp4/webm/mkv decode from ~6-7%.
    """
    proc = await asyncio.create_subprocess_exec(
        _FFMPEG,
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-c:v",
        "mjpeg",
        "-q:v",
        "2",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate(data)  # write all + EOF, read to completion
    return out if out[:3] == _JPEG_MAGIC else None


async def _extract_frame_streaming(url: str) -> bytes:
    """Extract frame 0 while downloading only as much of `url` as ffmpeg needs.

    One download connection feeds a growing buffer. Each time the buffer crosses
    a size threshold we spawn a fresh ffmpeg on the buffer-so-far (with EOF),
    forcing an early decode attempt. The first success stops the download — so a
    faststart-mp4/webm/mkv typically transfers ~6-7% of the file, never touching
    disk. A moov-at-end mp4 can't decode from a pipe at all (the index sits at
    the end and ffmpeg must seek back to it), so it consumes the full stream and
    falls back to the already-buffered bytes via a seekable temp file — no second
    download.
    """
    buf = bytearray()
    thresholds = list(_TRY_AT_BYTES)

    async with _dl_client.stream("GET", url) as resp:
        resp.raise_for_status()
        async for chunk in resp.aiter_bytes(_DL_CHUNK):
            buf.extend(chunk)
            if thresholds and len(buf) >= thresholds[0]:
                thresholds.pop(0)
                jpeg = await _try_decode_prefix(bytes(buf))
                if jpeg:
                    logger.info("streamed frame after %d KB (partial)", len(buf) // 1024)
                    return jpeg

    # Stream exhausted. One last pipe attempt on the whole file...
    jpeg = await _try_decode_prefix(bytes(buf))
    if jpeg:
        logger.info("streamed frame after %d KB (full file)", len(buf) // 1024)
        return jpeg

    # ...still nothing: moov-at-end mp4. Decode the buffered bytes from a
    # seekable temp file — no second download.
    logger.info("pipe undecodable (moov@end); seekable-temp fallback (%d KB)", len(buf) // 1024)
    with NamedTemporaryFile(suffix=".mp4") as tmp:
        tmp.write(buf)
        tmp.flush()
        return await asyncio.get_running_loop().run_in_executor(None, _extract_frame_from_file, tmp.name)


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
    logger.info("video_to_url: streaming frame from file %s", attachment.file_unique_id)
    # get_file() is a small metadata call; File.file_path is the full HTTPS URL on
    # Telegram's file server. We stream that ourselves and stop once ffmpeg has the
    # first frame — typically ~6-7% of the file for mp4/webm/mkv, no disk, no full DL.
    video_file = await attachment.get_file(read_timeout=_FILE_TIMEOUT, connect_timeout=_FILE_TIMEOUT)
    if not video_file.file_path:
        raise ValueError("Telegram returned no file_path for the video")
    frame_bytes = await _extract_frame_streaming(video_file.file_path)
    logger.info("video_to_url: got frame in %.1fs", time() - t0)

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
    photo_file = await attachment.get_file(read_timeout=_FILE_TIMEOUT, connect_timeout=_FILE_TIMEOUT)
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
