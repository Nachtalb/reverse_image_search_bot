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
import re
from collections.abc import Callable
from pathlib import Path

from reverse_image_search_bot import settings
from reverse_image_search_bot.abuse_report import crypto
from reverse_image_search_bot.config import abuse

logger = logging.getLogger("abuse.prepare")


def upload_dir() -> Path | None:
    p = settings.UPLOADER.get("configuration", {}).get("path")
    return Path(p) if p else None


def cipher_dir(report_uuid: str) -> Path | None:
    """Directory holding a report's encrypted image ciphertext (under the PVC).

    Mirrors how videos are stored: only FILED files' bytes ever move into
    SQLite, so an open report keeps its ciphertext on disk and the DB row just
    points at it.
    """
    updir = upload_dir()
    if updir is None:
        return None
    d = updir / "report_files" / report_uuid
    d.mkdir(parents=True, exist_ok=True)
    return d


def blob_ciphertext(blob: dict) -> bytes | None:
    """The encrypted bytes of a blob, wherever they live (disk or DB).

    Open reports keep ciphertext on disk (``cipher_path``); filed ones hold it
    in the ``ciphertext`` column. Returns None if the on-disk file is missing.
    """
    path = blob.get("cipher_path")
    if path:
        updir = upload_dir()
        if updir is None:
            return None
        fp = updir / path
        return fp.read_bytes() if fp.is_file() else None
    ct = blob.get("ciphertext")
    return bytes(ct) if ct else None


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


# Cloudflare CSAM reports list our public file URLs like
#   https://ris.naa.gg/f/AQADsAxrG35d6EZ9.jpg
# (often defanged: hxxps://ris.naa[.]gg/f/…). The /f/<file> segment is never
# defanged, so match the filename right after /f/.
_FILE_URL_RE = re.compile(r"/f/([A-Za-z0-9_\-]+\.[A-Za-z0-9]+)")
# Admin-forward caption tags; cid/gid are rendered abs() so re-negate them.
_TAG_RE = re.compile(r"^#(uid|cid|gid)(\d+)$")
# Target-shaped token in a multi-token paste: a bare id, an @username, or a
# bare filename (``<file_unique_id>.<ext>``).
_TARGETISH_RE = re.compile(r"^(-?\d+|@\w+|[A-Za-z0-9_\-]+\.[A-Za-z0-9]+)$")


def resolve_targets(text: str) -> tuple[list[int], list[str]]:
    """Resolve ANY blob of text into uploader user ids + unresolvable tokens.

    Accepts a single token (user id, @username, filename, ``#uid…`` tag) or a
    whole pasted Cloudflare report containing many file URLs — each token is
    resolved independently and the user ids are de-duplicated in order, so one
    paste yields one report round per unique uploader.

    In a multi-token paste only target-SHAPED tokens are considered (file URL,
    ``#uid`` tag, bare id, ``@username``, ``name.ext``), so surrounding prose
    ("URLs:", "Hi Nick") is neither resolved nor reported as unknown.
    """
    tokens = [t.strip().strip(".,;:()[]<>\"'") for t in re.split(r"[\s,;]+", text or "")]
    tokens = [t for t in tokens if t]
    lone = len(tokens) == 1
    ids: list[int] = []
    unknown: list[str] = []
    for tok in tokens:
        url = _FILE_URL_RE.search(tok)
        tag = _TAG_RE.match(tok)
        if url:
            tok = url.group(1)
            uid = abuse.find_user_by_filename(tok)
        elif tag:
            uid = -int(tag.group(2)) if tag.group(1) in ("cid", "gid") else int(tag.group(2))
        elif lone or _TARGETISH_RE.match(tok):
            uid = resolve_user(tok)
        else:
            continue
        if uid is None:
            if tok not in unknown:
                unknown.append(tok)
        elif uid not in ids:
            ids.append(uid)
    return ids, unknown


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
        error: str | None = None,
        existing_uuid: str | None = None,
        filed_uuid: str | None = None,
        filed_ncmec_id: int | None = None,
    ) -> None:
        self.report_uuid = report_uuid
        self.p1 = p1
        self.encrypted = encrypted
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


def _encrypt_and_remove(
    report_uuid: str, batch: list, key: bytes, progress: Callable[[int, int], None] | None = None
) -> int:
    """Encrypt (file_row, path) pairs into report blobs, deleting each plaintext.

    The ciphertext is written to disk (``report_files/<uuid>/``) and the DB row
    only points at it — nothing enters SQLite until the report is actually
    FILED. The plaintext is unlinked only AFTER its ciphertext is on disk and
    the row committed, so a crash mid-round can never lose a file: at worst it
    stays on disk and is picked up again. Taking the file offline is the point
    of preparing a report — while a round is open the material must not be
    publicly reachable.

    ``progress`` (optional) is called with ``(done, total)`` after each file;
    a big user/group takes a while and the admin wants to see it move.
    """
    cdir = cipher_dir(report_uuid)
    if cdir is None:
        return 0
    encrypted = 0
    total = len(batch)
    for f, fp in batch:
        try:
            data = fp.read_bytes()
        except Exception:
            logger.warning("failed to read %s", fp, exc_info=True)
            continue
        nonce, ct = crypto.encrypt_file(data, key)
        cipher_name = f"{f['file_unique_id']}.enc"
        (cdir / cipher_name).write_bytes(ct)
        abuse.add_report_blob(
            report_uuid,
            file_unique_id=f["file_unique_id"],
            saved_filename=f["saved_filename"],
            nonce=nonce,
            cipher_path=f"report_files/{report_uuid}/{cipher_name}",
            plaintext_sha256=crypto.sha256_hex(data),
        )
        try:
            fp.unlink()
        except Exception:
            logger.warning("failed to remove plaintext %s", fp, exc_info=True)
        encrypted += 1
        if progress is not None:
            progress(encrypted, total)
    return encrypted


def restore_report_files(report_uuid: str, p1: str) -> str | None:
    """Decrypt a report's blobs back onto disk. Returns an error string, or None.

    The inverse of preparing: cancelling a round means the files were fine, so
    they go back where they were. Verifies P1 against every blob's stored hash
    BEFORE writing anything — a wrong key must not scatter garbage into the
    upload directory.
    """
    updir = upload_dir()
    if updir is None:
        return "no upload path configured"
    key = crypto.derive_key(p1)
    plaintexts: list[tuple[Path, bytes]] = []
    for b in abuse.report_blobs(report_uuid):
        ct = blob_ciphertext(b)
        if ct is None:
            logger.warning("ciphertext missing for blob %s — cannot restore", b["id"])
            continue
        try:
            data = crypto.decrypt_file(bytes(b["nonce"]), ct, key)
        except Exception:
            return "image key (P1) incorrect"
        if crypto.sha256_hex(data) != b["plaintext_sha256"]:
            return "image key (P1) incorrect"
        plaintexts.append((updir / b["saved_filename"], data))
    for fp, data in plaintexts:
        try:
            fp.write_bytes(data)
        except Exception:
            logger.warning("failed to restore %s", fp, exc_info=True)
    return None


def purge_cipher_dir(report_uuid: str) -> None:
    """Delete a report's on-disk ciphertext directory (and its contents)."""
    updir = upload_dir()
    if updir is None:
        return
    d = updir / "report_files" / report_uuid
    if not d.is_dir():
        return
    for fp in d.iterdir():
        try:
            fp.unlink()
        except Exception:
            logger.warning("failed to delete ciphertext %s", fp, exc_info=True)
    try:
        d.rmdir()
    except Exception:
        logger.warning("failed to remove cipher dir %s", d, exc_info=True)


def delete_user_files(user_id: int) -> int:
    """Delete every on-disk file of a user. Returns how many were removed.

    Banning is the end of the line: nothing of theirs stays publicly reachable.
    That includes the still-ENCRYPTED leftovers of any report of theirs that was
    never filed — an open round's ciphertext is deleted along with its blob rows.
    Filed reports are untouched: their ciphertext moved into the DB at filing
    time and is the evidence.
    """
    updir = upload_dir()
    if updir is None:
        return 0
    removed = 0
    for f in abuse.files_for_user(user_id):
        fp = updir / f["saved_filename"]
        try:
            if fp.is_file():
                fp.unlink()
                removed += 1
        except Exception:
            logger.warning("failed to delete %s on ban", fp, exc_info=True)
    for rep in abuse.reports_for_user(user_id):
        if rep["status"] == abuse.REPORT_FILED:
            continue
        abuse.purge_report_blobs(rep["report_uuid"])
        purge_cipher_dir(rep["report_uuid"])
    return removed


def prepare_report(user_id: int, progress: Callable[[int, int], None] | None = None) -> PrepareResult:
    """Gather → encrypt → create a ``ready`` report for ``user_id``.

    Returns a :class:`PrepareResult`. On success it carries the new
    ``report_uuid``, the one-time image key ``p1`` (shown once, never stored),
    and the ``encrypted`` file count.

    EVERY on-disk file of the user is encrypted into the report and its
    plaintext removed from disk, so opening a report takes the material offline
    for as long as the round is open. The ciphertext lives on disk too — only
    FILED files ever enter the DB. Cancelling restores the files; filing moves
    the reported ciphertext into the DB and deletes the rest.

    ``progress`` (optional) receives ``(done, total)`` per encrypted file — a
    user or group with many uploads takes a while.
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
    encrypted = _encrypt_and_remove(report_uuid, present, key, progress)
    abuse.set_report_status(report_uuid, abuse.REPORT_READY)
    return PrepareResult(report_uuid=report_uuid, p1=p1, encrypted=encrypted)
