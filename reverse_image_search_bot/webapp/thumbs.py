"""Lazy thumbnails for the search-history Mini App.

A thumbnail is produced the first time someone actually LOOKS at an entry, never
in bulk: a backfilled history can hold tens of thousands of uploads, and
pre-rendering them all would be a huge amount of work for images nobody opens.

They live in a ``thumbs/`` SUBDIRECTORY of the upload dir, which matters:
``privacy.sweep_expired_uploads`` walks only the top level and skips every
subdirectory, so a thumbnail survives the plaintext retention sweep and history
stays visual after the original upload is gone. That also makes the thumbnail
personal data with its own lifetime — ``privacy.erase`` deletes it.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from reverse_image_search_bot.abuse_report.prepare import upload_dir

logger = logging.getLogger(__name__)

# Big enough to look sharp on a phone's list row, small enough that a full
# history costs little; WebP because it is roughly half the bytes of JPEG here.
THUMB_SIZE = (320, 320)
THUMB_QUALITY = 80


def thumbs_dir() -> Path | None:
    """The thumbnail directory, created on demand. None when no uploader path."""
    updir = upload_dir()
    if updir is None:
        return None
    d = updir / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumb_path(file_unique_id: str) -> Path | None:
    d = thumbs_dir()
    return None if d is None else d / f"{file_unique_id}.webp"


def _source_path(saved_filename: str) -> Path | None:
    updir = upload_dir()
    if updir is None or not saved_filename:
        return None
    # Guard the join: saved_filename comes from the DB, and a traversal there
    # must not be able to read outside the upload dir.
    candidate = (updir / Path(saved_filename).name).resolve()
    if candidate.parent != updir.resolve():
        return None
    return candidate


def get_or_create(file_unique_id: str, saved_filename: str | None) -> Path | None:
    """Return a cached thumbnail, making it first if the original is still there.

    None means "no image to show" — either the upload was swept by retention or
    it could not be decoded. Callers render a placeholder; this is expected, not
    an error.
    """
    dest = thumb_path(file_unique_id)
    if dest is None:
        return None
    if dest.exists():
        return dest
    if not saved_filename:
        return None
    src = _source_path(saved_filename)
    if src is None or not src.is_file():
        return None
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail(THUMB_SIZE)
            im.save(dest, "WEBP", quality=THUMB_QUALITY)
    except Exception:
        # A corrupt or unsupported upload is not a bug worth paging anyone over,
        # and WARNING+ goes to the admins over Telegram.
        logger.info("thumbs: could not render %s", saved_filename, exc_info=True)
        dest.unlink(missing_ok=True)
        return None
    return dest


def delete_for_files(file_unique_ids: list[str]) -> int:
    """Remove thumbnails for the given files (erasure path)."""
    removed = 0
    for fid in file_unique_ids:
        path = thumb_path(fid)
        if path is not None and path.exists():
            path.unlink(missing_ok=True)
            removed += 1
    return removed
