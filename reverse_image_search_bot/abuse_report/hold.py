"""Holding uploads from watchlisted users, encrypted at rest.

A user under investigation or already banned keeps uploading. Those files must
not be published — a banned user's media never gets a public URL at all — but
they are exactly what the next report round needs, so throwing them away is
wrong too.

They are therefore AES-GCM encrypted the moment they arrive and written under
``held/<user_id>/`` on the upload PVC. The static sidecar serves that PVC, so
plaintext there would be reachable; ciphertext is not, which is the whole point.

The key is derived from ``REPORT_PAGE_PASSWORD`` — the one long-lived secret this
deployment already has. It is NOT P1: P1 is per-report, shown once and never
stored, so it cannot exist at upload time. ``prepare_report`` decrypts each held
file with this key and immediately re-encrypts it under the round's P1, so held
material is only ever readable by the server, never by the network.
"""

from __future__ import annotations

import logging
from pathlib import Path

from reverse_image_search_bot import settings
from reverse_image_search_bot.abuse_report import crypto
from reverse_image_search_bot.abuse_report.prepare import upload_dir

logger = logging.getLogger("abuse.hold")


def hold_key() -> bytes | None:
    """The at-rest key for held files, or None when no page password is set.

    Without it we cannot encrypt, and writing plaintext into the served upload
    directory is not an acceptable fallback — the caller must skip holding.
    """
    if not settings.REPORT_PAGE_PASSWORD:
        return None
    return crypto.derive_key(settings.REPORT_PAGE_PASSWORD)


def hold_dir(user_id: int) -> Path | None:
    updir = upload_dir()
    if updir is None:
        return None
    d = updir / "held" / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def store(user_id: int, file_unique_id: str, data: bytes) -> tuple[str, bytes, str] | None:
    """Encrypt and park an upload. Returns ``(path, nonce, sha256)`` or None.

    ``path`` is relative to the upload dir, so it resolves the same way a normal
    ``saved_filename`` does.
    """
    key = hold_key()
    d = hold_dir(user_id)
    if key is None or d is None:
        logger.warning("cannot hold %s: no page password or no upload path configured", file_unique_id)
        return None
    nonce, ct = crypto.encrypt_file(data, key)
    (d / f"{file_unique_id}.enc").write_bytes(ct)
    return f"held/{user_id}/{file_unique_id}.enc", nonce, crypto.sha256_hex(data)


def load(file_row: dict) -> bytes | None:
    """Decrypt a held file back to plaintext. None if it is gone or unreadable."""
    key = hold_key()
    updir = upload_dir()
    path = file_row.get("hold_path")
    if key is None or updir is None or not path:
        return None
    fp = updir / path
    if not fp.is_file():
        return None
    try:
        data = crypto.decrypt_file(bytes(file_row["hold_nonce"]), fp.read_bytes(), key)
    except Exception:
        logger.warning("held file %s failed to decrypt", path, exc_info=True)
        return None
    if crypto.sha256_hex(data) != file_row["hold_sha256"]:
        logger.warning("held file %s failed its hash check", path)
        return None
    return data


def drop(file_row: dict) -> None:
    """Delete a held file's ciphertext (it has moved into a report round)."""
    updir = upload_dir()
    path = file_row.get("hold_path")
    if updir is None or not path:
        return
    try:
        fp = updir / path
        if fp.is_file():
            fp.unlink()
    except Exception:
        logger.warning("failed to delete held file %s", path, exc_info=True)
