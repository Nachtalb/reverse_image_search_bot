"""Lazy fetch + encrypt of the ORIGINAL uploaded video for a report blob.

When an admin opens a report, video-backed images can have their real source
video pulled from Telegram on demand (best-effort, ≤20 MB — the Bot API's hard
download ceiling) and stored **encrypted on disk**. The raw video plaintext is
never written to disk: we download into memory, AES-256-GCM encrypt with the
report's image key (P1), and write only the ciphertext. Videos are large, so the
ciphertext lives on the PVC (not in SQLite); the DB row keeps the nonce, hash,
relative path and display filename.

file_id stays valid indefinitely; only the download URL (file_path from getFile)
expires (~1h), so we always re-resolve it at fetch time. A deleted message is the
one unavoidable loss — get_file then fails and we leave the blob image-only.
"""

from __future__ import annotations

import logging
from pathlib import Path

from reverse_image_search_bot import settings
from reverse_image_search_bot.abuse_report import crypto
from reverse_image_search_bot.commands.utils import MAX_TELEGRAM_FILE_SIZE, _dl_client
from reverse_image_search_bot.config import abuse

logger = logging.getLogger("abuse.video")


def video_dir() -> Path | None:
    """Directory for encrypted video ciphertext (under the upload PVC path)."""
    base = settings.UPLOADER.get("configuration", {}).get("path")
    if not base:
        return None
    d = Path(base) / "report_videos"
    d.mkdir(parents=True, exist_ok=True)
    return d


class VideoFetchResult:
    def __init__(self, *, ok: bool, reason: str = "", filename: str = "") -> None:
        self.ok = ok
        self.reason = reason
        self.filename = filename


async def fetch_and_encrypt_video(bot, blob: dict, p1: str) -> VideoFetchResult:
    """Download the original video for ``blob`` and store it encrypted on disk.

    ``bot`` is a PTB Bot. ``p1`` is the report's image key (same key the images
    are encrypted with). Returns a result describing success or why it was
    skipped (no file_id, not a video, too large, deleted, download error).
    Idempotent: if the blob already has a video, returns ok immediately.
    """
    if blob.get("video_filename"):
        return VideoFetchResult(ok=True, filename=blob["video_filename"])

    rec = abuse.file_by_unique_id(blob["file_unique_id"])
    if not rec or not rec.get("file_id"):
        return VideoFetchResult(ok=False, reason="no file_id recorded for this upload")
    if (rec.get("file_type") or "") not in ("video", "gif", "sticker", "document"):
        # Only media that can be a video/animation. Photos have no source video.
        return VideoFetchResult(ok=False, reason="upload is not a video")

    vdir = video_dir()
    if vdir is None:
        return VideoFetchResult(ok=False, reason="no upload path configured")

    try:
        tg_file = await bot.get_file(rec["file_id"], read_timeout=15, connect_timeout=15)
    except Exception as e:
        logger.warning("get_file failed for %s: %s", blob["file_unique_id"], e)
        return VideoFetchResult(ok=False, reason="video no longer available (message deleted or expired)")

    size = getattr(tg_file, "file_size", None) or 0
    if size and size > MAX_TELEGRAM_FILE_SIZE:
        return VideoFetchResult(
            ok=False, reason=f"video is {size // 1024 // 1024} MB — over Telegram's 20 MB bot-download limit"
        )
    if not tg_file.file_path:
        return VideoFetchResult(ok=False, reason="Telegram returned no download path")

    # Stream into memory (bounded by the 20 MB limit), then encrypt.
    buf = bytearray()
    try:
        async with _dl_client.stream("GET", tg_file.file_path) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(64 * 1024):
                buf.extend(chunk)
                if len(buf) > MAX_TELEGRAM_FILE_SIZE:
                    return VideoFetchResult(ok=False, reason="video exceeded 20 MB mid-download")
    except Exception as e:
        logger.warning("video download failed for %s: %s", blob["file_unique_id"], e)
        return VideoFetchResult(ok=False, reason="download failed")

    data = bytes(buf)
    key = crypto.derive_key(p1)
    nonce, ct = crypto.encrypt_file(data, key)

    ext = (rec.get("saved_filename") or "").rsplit(".", 1)
    src_ext = ext[1] if len(ext) == 2 else "mp4"
    video_filename = f"{blob['file_unique_id']}.{src_ext}"
    cipher_name = f"{blob['file_unique_id']}.{src_ext}.enc"
    (vdir / cipher_name).write_bytes(ct)

    abuse.set_blob_video(
        blob["id"],
        video_path=f"report_videos/{cipher_name}",
        video_nonce=nonce,
        video_sha256=crypto.sha256_hex(data),
        video_filename=video_filename,
    )
    logger.info("stored encrypted video for blob %s (%d KB)", blob["id"], len(data) // 1024)
    return VideoFetchResult(ok=True, filename=video_filename)
