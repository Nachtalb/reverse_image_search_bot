"""Admin commands for the abuse-report pipeline: /report and /reports.

``/report <user_id|@username|filename>`` gathers a user's still-on-disk files,
encrypts each into a DB blob with a one-time image key (P1), creates a report
row, and DMs the admin the report launch button + P1. The report page itself is
gated by a single global page password (``REPORT_PAGE_PASSWORD``, in Proton
Pass). The admin opens the Mini App to review, classify, and file with NCMEC.

``/reports`` opens the reports Mini App: a list of all reports (click to open /
work on one) plus a form to create a new report from a username or filename.
"""

from __future__ import annotations

import contextlib
import html
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update, WebAppInfo
from telegram.ext import ContextTypes

from reverse_image_search_bot import metrics, settings
from reverse_image_search_bot.abuse_report.prepare import prepare_report, resolve_user
from reverse_image_search_bot.config import abuse

logger = logging.getLogger("abuse.commands")

# Cloudflare CSAM reports list our public file URLs like
#   https://ris.naa.gg/f/AQADsAxrG35d6EZ9.jpg
# (often defanged: hxxps://ris.naa[.]gg/f/…). The /f/<file> path segment is never
# defanged, so match the filename right after /f/. Case-insensitive extension.
_CF_FILE_RE = re.compile(r"/f/([A-Za-z0-9_\-]+\.[A-Za-z0-9]+)")


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start an encrypted NCMEC report round for a user (by id, @username, or filename)."""
    assert update.message and update.message.text and update.effective_user
    metrics.commands_total.labels(command="report").inc()
    args = update.message.text.strip("/").split(" ")
    if len(args) < 2 or not args[1].strip():
        await update.message.reply_text("Usage: /report <user_id | @username | filename>")
        return

    arg = args[1].strip()
    user_id = resolve_user(arg)
    if user_id is None:
        await update.message.reply_text(f"No uploader found for: {arg}")
        return

    await start_report(update, context, user_id)


async def bulk_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bulk-check pasted Cloudflare file URLs and open a report per new uploader.

    Paste the ``URLs:`` line from a Cloudflare CSAM report (defanged or not). We
    regex out every ``/f/<file>`` name, resolve each to its uploader, and for each
    UNIQUE user with files still on disk create one encrypted report round —
    then DM a combined list of the new reports with each user's image key (P1).
    Users whose files were already filed (or already have an active report) are
    listed as skipped, so you can see at a glance what's new vs already handled.
    """
    assert update.message and update.message.text and update.effective_user
    metrics.commands_total.labels(command="bulk_report").inc()

    text = update.message.text
    filenames = list(dict.fromkeys(_CF_FILE_RE.findall(text)))  # de-dup, keep order
    if not filenames:
        await update.message.reply_text(
            "No file URLs found. Paste the Cloudflare report's URLs line, e.g.\n"
            "/bulkreport URLs: https://ris.naa.gg/f/AQAD….jpg, https://ris.naa.gg/f/AgAD….jpg"
        )
        return

    # Map each file → uploader. Group filenames per user; track files with no
    # known uploader separately.
    users_files: dict[int, list[str]] = {}
    unknown: list[str] = []
    for fn in filenames:
        uid = abuse.find_user_by_filename(fn)
        if uid is None:
            unknown.append(fn)
        else:
            users_files.setdefault(uid, []).append(fn)

    created: list[dict] = []  # {user_id, username, p1, uuid, encrypted}
    skipped: list[str] = []  # human-readable lines

    for uid in users_files:
        user = abuse.get_user(uid) or {}
        uname = f"@{user['username']}" if user.get("username") else "—"
        result = prepare_report(uid)
        if result.ok:
            created.append(
                {
                    "user_id": uid,
                    "username": uname,
                    "p1": result.p1 or "",
                    "uuid": result.report_uuid,
                    "encrypted": result.encrypted,
                }
            )
        else:
            # Already-filed / active-report / nothing-on-disk — surface the reason.
            reason = (result.error or "could not prepare").split("\n")[0]
            skipped.append(f"• <code>{uid}</code> ({html.escape(uname)}) — {html.escape(reason)}")

    # Point the admin's menu button at the reports console so they can open the
    # new reports (each unlocked with the global page password + its P1 below).
    console_url = f"{settings.REPORT_BASE_URL}/report/console" if settings.REPORT_BASE_URL else None
    if console_url:
        with contextlib.suppress(Exception):
            await context.bot.set_chat_menu_button(
                chat_id=update.effective_user.id,
                menu_button=MenuButtonWebApp(text="Reports", web_app=WebAppInfo(url=console_url)),
            )

    # Build the combined report. Header stats first.
    lines = [
        f"<b>Bulk report</b> — {len(filenames)} file(s), {len(users_files)} uploader(s).",
        f"<b>New reports:</b> {len(created)} · <b>Skipped:</b> {len(skipped)} · <b>Unknown files:</b> {len(unknown)}",
    ]
    if created:
        lines.append("")
        lines.append("<b>🆕 New reports (open via the Reports menu button):</b>")
        for c in created:
            url = f"{settings.REPORT_BASE_URL}/report/{c['uuid']}" if settings.REPORT_BASE_URL else ""
            lines.append(
                f"• <code>{c['user_id']}</code> ({html.escape(c['username'])}) — "
                f"{c['encrypted']} file(s)\n"
                f"  <b>P1:</b> <code>{html.escape(c['p1'])}</code>" + (f"\n  {html.escape(url)}" if url else "")
            )
    if skipped:
        lines.append("")
        lines.append("<b>⏭ Skipped (already filed / active / nothing on disk):</b>")
        lines.extend(skipped)
    if unknown:
        lines.append("")
        lines.append("<b>❓ Unknown files (no uploader on record):</b>")
        lines.append(html.escape(", ".join(unknown)))

    # 4096-char safe chunking on line boundaries.
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 4000:
            await update.message.reply_html(chunk, disable_web_page_preview=True)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await update.message.reply_html(chunk, disable_web_page_preview=True)


async def start_report(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Create an encrypted report round for an already-resolved ``user_id``.

    Reusable seam: callers (the public ``/report`` command, or a deploy-side
    reply/#uid wrapper) resolve the target user id however they like, then hand
    it here for the file-gather → encrypt → DM flow.
    """
    assert update.message and update.effective_user

    result = prepare_report(user_id)
    if not result.ok:
        msg = result.error or "Could not prepare a report."
        if result.existing_uuid and settings.REPORT_BASE_URL:
            msg += f"\n{settings.REPORT_BASE_URL}/report/{result.existing_uuid}"
        await update.message.reply_text(msg)
        return

    report_uuid = result.report_uuid
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
        f"Encrypted <b>{result.encrypted}</b> file(s).\n\n"
        f"<b>Image key (P1):</b> <code>{html.escape(result.p1 or '')}</code>\n\n"
        f"{launch}\n\n"
        f"<i>Use the global page password to open the report, then P1 to decrypt "
        f"the images. P1 is not stored — if you lose it the thumbnails can't be "
        f"shown (the files still exist on disk until you file/cancel). On filing, "
        f"the plaintext files are deleted from disk but the encrypted copies stay "
        f"in the DB, linked to the report, for further inspection.</i>",
        disable_web_page_preview=True,
    )


async def reports_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the reports Mini App (list + create), and echo a text summary."""
    assert update.message and update.effective_user
    metrics.commands_total.labels(command="reports").inc()

    # Point the admin's menu button at the reports list Mini App so it opens with
    # signed initData the webview can validate.
    menu_button_set = False
    if settings.REPORT_BASE_URL:
        with contextlib.suppress(Exception):
            await context.bot.set_chat_menu_button(
                chat_id=update.effective_user.id,
                menu_button=MenuButtonWebApp(
                    text="Reports", web_app=WebAppInfo(url=f"{settings.REPORT_BASE_URL}/report/console")
                ),
            )
            menu_button_set = True

    reports = abuse.all_reports()
    count = len(reports)
    if menu_button_set:
        summary = "No reports on file yet." if not count else f"{count} report{'s' if count != 1 else ''} on file."
        await update.message.reply_html(
            f"{summary} Tap the <b>Reports</b> menu button (bottom-left ⊞) to open the reports console "
            "(list, open a report, or create a new one)."
        )
        return

    # Fallback when no menu button could be set (no REPORT_BASE_URL): give a link.
    url = f"{settings.REPORT_BASE_URL}/report/console" if settings.REPORT_BASE_URL else None
    if url:
        await update.message.reply_html(
            f"{count} report{'s' if count != 1 else ''} on file.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Open reports console", url=url)]]),
        )
    else:
        await update.message.reply_html(
            f"{count} report{'s' if count != 1 else ''} on file. (Reports console URL not configured.)"
        )
