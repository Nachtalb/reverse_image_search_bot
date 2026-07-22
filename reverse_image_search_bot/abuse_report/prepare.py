"""Shared report-preparation core.

Gathering a user's still-on-disk files, encrypting each into a DB blob with a
one-time image key (P1), and creating a ``ready`` report row is needed from two
places: the ``/report`` admin command and the ``/reports`` Mini App's "create
report" form. This module is the single implementation both call, so the two
entry points can never diverge.

No Telegram imports here — only the DB (``config.abuse``), crypto, and the
upload path from ``settings``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from reverse_image_search_bot import settings
from reverse_image_search_bot.abuse_report import crypto
from reverse_image_search_bot.config import abuse

logger = logging.getLogger("abuse.prepare")

# Hard cap on files encrypted into a report round at once. Reports with more
# on-disk uploads get a "show more" in the webview that prepares the next batch.
PREPARE_BATCH = 25


def upload_dir() -> Path | None:
    p = settings.UPLOADER.get("configuration", {}).get("path")
    return Path(p) if p else None


def resolve_user(arg: str) -> int | None:
    """Resolve a target user id from a raw token: numeric id, @username, or filename."""
    arg = arg.strip()
    if not arg:
        return None
    if arg.lstrip("-").isdigit():
        return int(arg)
    if arg.startswith("@"):
        return abuse.find_user_by_username(arg)
    # Try username first (bare word), then fall back to a filename lookup.
    return abuse.find_user_by_username(arg) or abuse.find_user_by_filename(arg)


class PrepareResult:
    """Outcome of :func:`prepare_report`.

    Exactly one of ``report_uuid`` (success) or ``error`` (failure) is set.
    ``existing_uuid`` is set when the failure is "an active report already
    exists" so the caller can link to it instead.
    """

    def __init__(
        self,
        *,
        report_uuid: str | None = None,
        p1: str | None = None,
        encrypted: int = 0,
        remaining: int = 0,
        error: str | None = None,
        existing_uuid: str | None = None,
        filed_uuid: str | None = None,
        filed_ncmec_id: int | None = None,
    ) -> None:
        self.report_uuid = report_uuid
        self.p1 = p1
        self.encrypted = encrypted
        # Files still on disk but beyond the PREPARE_BATCH cap — preparable via
        # the webview's "show more".
        self.remaining = remaining
        self.error = error
        self.existing_uuid = existing_uuid
        # Set when the failure is "already filed with NCMEC" so the caller can
        # show the filed report id + link to it instead of re-parsing the prose.
        self.filed_uuid = filed_uuid
        self.filed_ncmec_id = filed_ncmec_id

    @property
    def ok(self) -> bool:
        return self.report_uuid is not None


def _present_files(user_id: int) -> tuple[list, int, int]:
    """Files still on disk for a user, excluding cleared ones.

    Returns ``(present, recorded, cleared)`` where ``present`` is a list of
    ``(file_row, path)``, ``recorded`` the total recorded file count, and
    ``cleared`` how many on-disk files were skipped as cleared.
    """
    files = abuse.files_for_user(user_id)
    updir = upload_dir()
    present = []
    cleared = 0
    for f in files:
        if not updir:
            continue
        fp = updir / f["saved_filename"]
        if not fp.is_file():
            continue
        if f.get("cleared_at"):
            cleared += 1
            continue
        present.append((f, fp))
    return present, len(files), cleared


def _encrypt_batch(report_uuid: str, batch: list, key: bytes) -> int:
    """Encrypt a batch of (file_row, path) into report blobs. Returns count."""
    encrypted = 0
    for f, fp in batch:
        try:
            data = fp.read_bytes()
        except Exception:
            logger.warning("failed to read %s", fp, exc_info=True)
            continue
        nonce, ct = crypto.encrypt_file(data, key)
        abuse.add_report_blob(
            report_uuid,
            file_unique_id=f["file_unique_id"],
            saved_filename=f["saved_filename"],
            nonce=nonce,
            ciphertext=ct,
            plaintext_sha256=crypto.sha256_hex(data),
        )
        encrypted += 1
    return encrypted


def prepare_report(user_id: int) -> PrepareResult:
    """Gather → encrypt → create a ``ready`` report for ``user_id``.

    Returns a :class:`PrepareResult`. On success it carries the new
    ``report_uuid``, the one-time image key ``p1`` (shown once, never stored),
    and the ``encrypted`` file count. At most ``PREPARE_BATCH`` files are
    encrypted; the rest are reported via ``remaining`` (the webview's
    "show more" prepares them in later batches).
    """
    if not settings.REPORT_BASE_URL:
        return PrepareResult(error="Report server is not configured (REPORT_BASE_URL unset).")

    existing = abuse.active_report_for_user(user_id)
    if existing:
        return PrepareResult(
            error=f"An active report already exists for user {user_id} (status: {existing['status']}).",
            existing_uuid=existing["report_uuid"],
        )

    present, recorded, cleared = _present_files(user_id)
    if not present:
        if cleared:
            return PrepareResult(
                error=f"All {cleared} remaining file(s) of user {user_id} are marked cleared — nothing to report."
            )
        filed = abuse.latest_filed_report_for_user(user_id)
        if filed and filed.get("ncmec_report_id"):
            n = filed.get("reported_files", 0)
            others = f" along with {n - 1} other file(s)" if n and n > 1 else ""
            return PrepareResult(
                error=(
                    f"User {user_id} was already filed with NCMEC in report "
                    f"#{filed['ncmec_report_id']}{others}. The plaintext files were "
                    f"deleted from disk after filing (the encrypted copies are kept "
                    f"in that report) — nothing new to report."
                ),
                filed_uuid=filed["report_uuid"],
                filed_ncmec_id=filed["ncmec_report_id"],
            )
        return PrepareResult(
            error=f"User {user_id} has {recorded} recorded file(s) but none are still on disk — nothing to report."
        )

    # P1 is the one-time image key — shown ONCE and never stored. The page
    # password is a single global secret (REPORT_PAGE_PASSWORD), not per-report.
    p1 = crypto.gen_password()
    report_uuid = crypto.gen_report_uuid()
    key = crypto.derive_key(p1)

    abuse.create_report(report_uuid, user_id, "")
    batch = present[:PREPARE_BATCH]
    encrypted = _encrypt_batch(report_uuid, batch, key)
    abuse.set_report_status(report_uuid, abuse.REPORT_READY)
    return PrepareResult(report_uuid=report_uuid, p1=p1, encrypted=encrypted, remaining=len(present) - len(batch))


def pending_files(report_uuid: str) -> int:
    """How many of the report user's on-disk, non-cleared files are NOT yet blobs."""
    rep = abuse.get_report(report_uuid)
    if not rep:
        return 0
    in_report = {b["file_unique_id"] for b in abuse.report_blobs(report_uuid)}
    present, _, _ = _present_files(rep["user_id"])
    return sum(1 for f, _ in present if f["file_unique_id"] not in in_report)


def extend_report(report_uuid: str, p1: str) -> PrepareResult:
    """Encrypt the next ``PREPARE_BATCH`` not-yet-included files into the report.

    ``p1`` must be the report's original image key — it is verified against an
    existing blob's hash before anything is encrypted, so a typo can't split the
    report across two keys.
    """
    rep = abuse.get_report(report_uuid)
    if not rep:
        return PrepareResult(error="report not found")
    key = crypto.derive_key(p1)
    blobs = abuse.report_blobs(report_uuid)
    if blobs:
        probe = blobs[0]
        try:
            data = crypto.decrypt_file(bytes(probe["nonce"]), bytes(probe["ciphertext"]), key)
        except Exception:
            return PrepareResult(error="image key (P1) incorrect")
        if crypto.sha256_hex(data) != probe["plaintext_sha256"]:
            return PrepareResult(error="image key (P1) incorrect")
    in_report = {b["file_unique_id"] for b in blobs}
    present, _, _ = _present_files(rep["user_id"])
    todo = [(f, fp) for f, fp in present if f["file_unique_id"] not in in_report]
    batch = todo[:PREPARE_BATCH]
    encrypted = _encrypt_batch(report_uuid, batch, key)
    return PrepareResult(report_uuid=report_uuid, encrypted=encrypted, remaining=len(todo) - len(batch))
