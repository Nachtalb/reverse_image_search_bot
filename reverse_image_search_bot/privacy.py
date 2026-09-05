"""User-facing data handling: retention sweep, data export, erasure.

Everything here treats report material as untouchable — encrypted evidence
lives in subdirectories of the upload dir and in ``report_blobs``; this module
only ever acts on plaintext uploads and the plain user/chat records.
"""

from __future__ import annotations

import logging
import time

from reverse_image_search_bot import settings
from reverse_image_search_bot.abuse_report.prepare import upload_dir

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
