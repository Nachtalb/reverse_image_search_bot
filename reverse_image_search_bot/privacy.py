"""User-facing data handling: retention sweep, data export, erasure.

Everything here treats report material as untouchable — encrypted evidence
lives in subdirectories of the upload dir and in ``report_blobs``; this module
only ever acts on plaintext uploads and the plain user/chat records.
"""

from __future__ import annotations

import datetime
import itertools
import json
import logging
import time
import zipfile
from pathlib import Path

from reverse_image_search_bot import settings
from reverse_image_search_bot.abuse_report.prepare import upload_dir
from reverse_image_search_bot.config import abuse
from reverse_image_search_bot.config.chat_config import forget_chat
from reverse_image_search_bot.config.db import load_config

logger = logging.getLogger(__name__)


def sweep_expired_uploads(now: float | None = None) -> int:
    """Unlink plaintext uploads older than ``FILE_RETENTION_DAYS``.

    Top level of the upload dir ONLY: every subdirectory there (``report_files/``,
    ``report_videos/``, ``held/``) is encrypted evidence with its own lifecycle.
    DB rows are kept — ``file_id`` lets a later report round re-fetch the file
    from Telegram.
    """
    updir = upload_dir()
    if updir is None or not updir.is_dir():
        return 0
    cutoff = (now if now is not None else time.time()) - settings.FILE_RETENTION_DAYS * 86400
    removed = 0
    for fp in updir.iterdir():
        try:
            if fp.is_file() and fp.stat().st_mtime < cutoff:
                fp.unlink()
                removed += 1
        except OSError:
            logger.info("retention: could not remove %s", fp, exc_info=True)
    return removed


# --- Takeout ------------------------------------------------------------------

# Telegram's bot upload ceiling per document. A larger archive is byte-split
# into <name>.zip.001, .002, … (7-Zip volume format; `cat` reassembles).
PART_BYTES = 50 * 1024 * 1024

_USER_FIELDS = ("user_id", "username", "first_name", "last_name", "language_code", "first_seen", "last_seen")
_CHAT_FIELDS = ("chat_id", "chat_type", "title", "username", "first_seen", "last_seen")
_FILE_FIELDS = (
    "file_unique_id",
    "original_filename",
    "file_type",
    "is_video",
    "upload_time",
    "caption",
    "user_id",
    "group_id",
    "channel_id",
)


def _subject_files(subject_id: int) -> list[dict]:
    return abuse.files_for_chat(subject_id) if subject_id < 0 else abuse.files_for_user(subject_id)


def _iso(ts: int | None) -> str | None:
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).isoformat() if ts else None


def export_data(subject_id: int) -> dict:
    """The JSON body of a takeout: profile, settings and upload records.

    Only plain record fields are copied — report state, bans, holds and fetch
    errors never leave the DB.
    """
    if subject_id < 0:
        chat = abuse.get_chat(subject_id) or {}
        who = {"chat": {k: chat.get(k) for k in _CHAT_FIELDS}}
    else:
        user = abuse.get_user(subject_id) or {}
        who = {"user": {k: user.get(k) for k in _USER_FIELDS}}
    for k in ("first_seen", "last_seen"):
        for v in who.values():
            v[k] = _iso(v.get(k))
    files = [{k: f.get(k) for k in _FILE_FIELDS} for f in _subject_files(subject_id)]
    for f in files:
        f["is_video"] = bool(f["is_video"])
        f["upload_time"] = _iso(f["upload_time"])
    return {
        "exported_at": datetime.datetime.now(datetime.UTC).isoformat(),
        **who,
        "settings": load_config(subject_id),
        "files": files,
    }


def build_takeout(subject_id: int, workdir: Path) -> list[Path]:
    """Write ``takeout-<id>-<date>.zip`` (split into volumes if needed) into ``workdir``."""
    stem = f"takeout-{abs(subject_id)}-{datetime.date.today().isoformat()}"
    archive = workdir / f"{stem}.zip"
    updir = upload_dir()
    linked = abuse.report_linked_file_ids(subject_id)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("data.json", json.dumps(export_data(subject_id), indent=2, ensure_ascii=False))
        for f in _subject_files(subject_id):
            fp = updir / f["saved_filename"] if updir else None
            if fp and fp.is_file() and f["file_unique_id"] not in linked:
                zf.write(fp, f"files/{f['saved_filename']}")
    if archive.stat().st_size <= PART_BYTES:
        return [archive]
    parts = []
    with archive.open("rb") as src:
        for n in itertools.count(1):
            chunk = src.read(PART_BYTES)
            if not chunk:
                break
            part = workdir / f"{stem}.zip.{n:03d}"
            part.write_bytes(chunk)
            parts.append(part)
    archive.unlink()
    return parts


# --- Erase --------------------------------------------------------------------


def erase(subject_id: int) -> None:
    """Remove a user's (or chat's) data, except whatever is tied to a report.

    Plaintext of files that no report references is unlinked. A user who was
    never reported loses their records and profile too; a reported user keeps
    them (retained for legal purposes). For a chat only its own row and settings
    go — the upload records belong to their uploaders.
    """
    updir = upload_dir()
    linked = abuse.report_linked_file_ids(subject_id)
    if updir:
        for f in _subject_files(subject_id):
            if f["file_unique_id"] not in linked:
                (updir / f["saved_filename"]).unlink(missing_ok=True)
    forget_chat(subject_id)
    if subject_id < 0:
        abuse.delete_chat_row(subject_id)
    elif not abuse.is_reported(subject_id):
        abuse.delete_user_rows(subject_id)
