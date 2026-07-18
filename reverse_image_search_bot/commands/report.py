"""Admin commands for the abuse-report pipeline: /report and /reports.

``/report <user_id|filename>`` gathers a user's still-on-disk files, encrypts
each into a DB blob with a one-time image key (P1), creates a report row, and DMs
the admin the report launch button + P1. The report page itself is gated by a
single global page password (``REPORT_PAGE_PASSWORD``, in Proton Pass). The admin
opens the Mini App to review, classify, and file with NCMEC.

``/reports`` lists all reports with their status.
"""

from __future__ import annotations

import contextlib
import html
import logging
from pathlib import Path

from telegram import MenuButtonWebApp, Update, WebAppInfo
from telegram.ext import ContextTypes

from reverse_image_search_bot import metrics, settings
from reverse_image_search_bot.abuse_report import crypto
from reverse_image_search_bot.config import abuse

logger = logging.getLogger("abuse.commands")


def _upload_dir() -> Path | None:
    p = settings.UPLOADER.get("configuration", {}).get("path")
    return Path(p) if p else None


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start an encrypted NCMEC report round for a user (by id or filename)."""
    assert update.message and update.message.text and update.effective_user
    metrics.commands_total.labels(command="report").inc()
    args = update.message.text.strip("/").split(" ")
    if len(args) < 2 or not args[1].strip():
        await update.message.reply_text("Usage: /report <user_id | filename>")
        return

    arg = args[1].strip()
    if arg.isdigit():
        user_id: int | None = int(arg)
    else:
        user_id = abuse.find_user_by_filename(arg)
        if user_id is None:
            await update.message.reply_text(f"No uploader found for file: {arg}")
            return

    await start_report(update, context, user_id)


async def start_report(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Create an encrypted report round for an already-resolved ``user_id``.

    Reusable seam: callers (the public ``/report`` command, or a deploy-side
    reply/#uid wrapper) resolve the target user id however they like, then hand
    it here for the file-gather → encrypt → DM flow.
    """
    assert update.message and update.effective_user

    if not settings.REPORT_BASE_URL:
        await update.message.reply_text(
            "Report server is not configured (REPORT_BASE_URL unset). Cannot create a report."
        )
        return

    existing = abuse.active_report_for_user(user_id)
    if existing:
        url = f"{settings.REPORT_BASE_URL}/report/{existing['report_uuid']}"
        await update.message.reply_text(
            f"An active report already exists for user {user_id} (status: {existing['status']}).\n{url}"
        )
        return

    files = abuse.files_for_user(user_id)
    updir = _upload_dir()
    present = []
    for f in files:
        if updir:
            fp = updir / f["saved_filename"]
            if fp.is_file():
                present.append((f, fp))
    if not present:
        await update.message.reply_text(
            f"User {user_id} has {len(files)} recorded file(s) but none are still on disk — nothing to report."
        )
        return

    # Generate the image key P1 — shown ONCE here and never stored. The page
    # password is a single global secret (REPORT_PAGE_PASSWORD, in Proton Pass),
    # so it is NOT generated or DMed per-report.
    p1 = crypto.gen_password()
    report_uuid = crypto.gen_report_uuid()
    key = crypto.derive_key(p1)

    abuse.create_report(report_uuid, user_id, "")

    encrypted = 0
    for f, fp in present:
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

    abuse.set_report_status(report_uuid, abuse.REPORT_READY)
    url = f"{settings.REPORT_BASE_URL}/report/{report_uuid}"

    # Point THIS admin's menu button at THIS report, so tapping it launches the
    # report as a Mini App with signed initData (which the webview validates).
    menu_button_set = False
    with contextlib.suppress(Exception):
        await context.bot.set_chat_menu_button(
            chat_id=update.effective_user.id,
            menu_button=MenuButtonWebApp(text="Open report", web_app=WebAppInfo(url=url)),
        )
        menu_button_set = True

    user = abuse.get_user(user_id) or {}
    uname = f"@{user['username']}" if user.get("username") else "—"
    launch = (
        "Tap the <b>Open report</b> menu button (bottom-left ⊞) to open it."
        if menu_button_set
        else f"Open via the report menu button: {html.escape(url)}"
    )
    await update.message.reply_html(
        f"<b>Report prepared</b> for user <code>{user_id}</code> ({html.escape(uname)})\n"
        f"Encrypted <b>{encrypted}</b> file(s).\n\n"
        f"<b>Image key (P1):</b> <code>{html.escape(p1)}</code>\n\n"
        f"{launch}\n\n"
        f"<i>Use the global page password to open the report, then P1 to decrypt "
        f"the images. P1 is not stored — if you lose it the thumbnails can't be "
        f"shown (the files still exist on disk until you file/cancel).</i>",
        disable_web_page_preview=True,
    )


async def reports_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all abuse reports and their status."""
    assert update.message
    metrics.commands_total.labels(command="reports").inc()
    reports = abuse.all_reports()
    if not reports:
        await update.message.reply_text("No reports on file.")
        return
    lines = ["<b>Abuse reports:</b>"]
    for r in reports:
        uname = f"@{r['username']}" if r.get("username") else str(r["user_id"])
        ncmec = f" · NCMEC #{r['ncmec_report_id']}" if r.get("ncmec_report_id") else ""
        lines.append(f"• <code>{r['report_uuid'][:8]}</code> {html.escape(uname)} — <b>{r['status']}</b>{ncmec}")
    # 4096-char safe chunking
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 4000:
            await update.message.reply_html(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await update.message.reply_html(chunk)
