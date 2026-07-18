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

from telegram import MenuButtonWebApp, Update, WebAppInfo
from telegram.ext import ContextTypes

from reverse_image_search_bot import metrics, settings
from reverse_image_search_bot.abuse_report.prepare import prepare_report, resolve_user
from reverse_image_search_bot.config import abuse

logger = logging.getLogger("abuse.commands")


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
    header = (
        "Tap the <b>Reports</b> menu button (bottom-left ⊞) to open the reports console "
        "(list, open a report, or create a new one)."
        if menu_button_set
        else "Reports console:"
    )
    if not reports:
        await update.message.reply_html(f"{header}\n\nNo reports on file yet.")
        return

    lines = [header, "", "<b>Abuse reports:</b>"]
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
