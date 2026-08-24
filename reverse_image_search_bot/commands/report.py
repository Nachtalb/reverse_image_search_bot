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

import asyncio
import contextlib
import html
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update, WebAppInfo
from telegram.ext import ContextTypes

from reverse_image_search_bot import metrics, settings
from reverse_image_search_bot.abuse_report.prepare import prepare_report, resolve_targets
from reverse_image_search_bot.config import abuse

logger = logging.getLogger("abuse.commands")

# Don't edit the progress message more often than this (Telegram rate limits
# edits, and a 500-file round would otherwise fire 500 edits).
PROGRESS_EVERY = 10


def _progress_pump(message, prefix: str):
    """Build a (done, total) callback that live-edits ``message``.

    ``prepare_report`` runs in a worker thread (asyncio.to_thread), so the
    callback cannot await — it schedules the edit back onto the running loop
    with ``run_coroutine_threadsafe`` and never blocks the encryption.
    """
    loop = asyncio.get_running_loop()

    def on_progress(done: int, total: int) -> None:
        if done != total and done % PROGRESS_EVERY:
            return
        text = f"{prefix} encrypting {done}/{total}…"
        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(_safe_edit(message, text), loop)

    return on_progress


async def _safe_edit(message, text: str) -> None:
    """Edit a status message, ignoring rate limits / identical-content errors."""
    with contextlib.suppress(Exception):
        await message.edit_text(text)


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prepare NCMEC report round(s).

    Accepts EITHER a single target (numeric user id, @username, group/channel id,
    or a filename) OR any blob of text containing Cloudflare file URLs
    (``https://ris.naa.gg/f/<file>`` — defanged or not, as pasted from a CSAM
    report). File URLs are regexed out, each resolved to its uploader, and one
    encrypted report round is created per UNIQUE new uploader. The reply is a
    compact status list: one line per user with an icon, id, username, and either
    the report password (P1) for a new report or the filed NCMEC report id.
    """
    assert update.message and update.message.text and update.effective_user
    metrics.commands_total.labels(command="report").inc()

    # Strip the leading /report (and any @botname) to get the raw argument text.
    raw = update.message.text
    body = re.sub(r"^/report(@\S+)?\s*", "", raw, count=1).strip()

    # Any input shape: a single token, a #uid tag, or a whole pasted Cloudflare
    # report full of file URLs — resolve_targets handles them uniformly.
    user_ids, unknown = resolve_targets(body)
    if not body:
        await update.message.reply_text(
            "Usage: /report <user_id | @username | group/channel id | filename>\n"
            "or paste Cloudflare file URLs (https://ris.naa.gg/f/…) to report each uploader."
        )
        return
    if not user_ids:
        await update.message.reply_text(f"No uploader found for: {', '.join(unknown) or body}")
        return

    await report_users(update, context, user_ids, unknown)


async def report_users(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_ids: list[int],
    unknown: list[str] | None = None,
) -> None:
    """Prepare a report for each user id and reply with the compact status list.

    Shared entry point: the public ``/report`` command (single token or bulk
    Cloudflare URLs) and the deploy-side wrapper (reply-to / #uid / group-channel
    expansion) both resolve target user ids their own way, then hand them here so
    the outcome list looks identical everywhere.
    """
    if not update.message:
        return
    rows: list[dict] = []  # {icon, user_id, username, detail, uuid?}
    uids = list(dict.fromkeys(user_ids))  # de-dup, preserve order
    # Encrypting a round takes a while (PBKDF2 + AES per file) — tell the admin
    # right away, and run the work off the event loop so nothing times out.
    status_msg = None
    with contextlib.suppress(Exception):
        status_msg = await update.message.reply_text(
            f"⏳ Preparing report{'s' if len(uids) != 1 else ''} for {len(uids)} user(s)…"
        )
    for uid in uids:
        user = abuse.get_user(uid) or {}
        uname = f"@{user['username']}" if user.get("username") else "—"
        # Plain text — _safe_edit uses edit_text (no parse_mode).
        prefix = f"⏳ user {uid} ({len(rows) + 1}/{len(uids)}) —" if len(uids) > 1 else "⏳"
        on_progress = _progress_pump(status_msg, prefix) if status_msg else None
        result = await asyncio.to_thread(prepare_report, uid, on_progress)
        if result.ok:
            rows.append(
                {
                    "icon": "🆕",
                    "user_id": uid,
                    "username": uname,
                    "detail": f"P1 <code>{html.escape(result.p1 or '')}</code> · {result.encrypted} file(s) offline",
                    "uuid": result.report_uuid,
                }
            )
        elif result.existing_uuid:
            rows.append(
                {
                    "icon": "⏳",
                    "user_id": uid,
                    "username": uname,
                    "detail": "active report open",
                    "uuid": result.existing_uuid,
                }
            )
        elif result.filed_ncmec_id:
            rows.append(
                {
                    "icon": "✅",
                    "user_id": uid,
                    "username": uname,
                    "detail": f"filed NCMEC #{result.filed_ncmec_id}",
                    "uuid": result.filed_uuid,
                }
            )
        else:
            rows.append({"icon": "⏭", "user_id": uid, "username": uname, "detail": "nothing to report", "uuid": None})

    if status_msg is not None:
        with contextlib.suppress(Exception):
            await status_msg.delete()
    await _send_report_summary(update, context, rows, unknown or [])


# Icon legend for the status list (kept compact; explained once in the footer).
_LEGEND = "🆕 new · ✅ already filed · ⏳ active · ⏭ nothing · ❓ unknown file"


async def _send_report_summary(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    rows: list[dict],
    unknown: list[str],
) -> None:
    """Render the compact per-user status list + wire up Mini App access.

    Menu button → the report to work on next (the first new/active report, else
    the reports console). In private chats each actionable row also gets its own
    ``web_app`` button that opens that specific report as a Mini App.
    """
    assert update.message and update.effective_user
    base = settings.REPORT_BASE_URL

    # Point the menu button at the most actionable report (new > active), else the
    # console — so the ⊞ button always opens something useful, even in groups.
    launch_uuid = next((r["uuid"] for r in rows if r["icon"] in ("🆕", "⏳") and r["uuid"]), None)
    menu_url = (
        f"{base}/report/{launch_uuid}" if (base and launch_uuid) else (f"{base}/report/console" if base else None)
    )
    menu_text = "Open report" if launch_uuid else "Reports"
    if menu_url:
        with contextlib.suppress(Exception):
            await context.bot.set_chat_menu_button(
                chat_id=update.effective_user.id,
                menu_button=MenuButtonWebApp(text=menu_text, web_app=WebAppInfo(url=menu_url)),
            )

    # web_app inline buttons only work in PRIVATE chats — offer per-report deep
    # links there; in groups the menu button above is the entry point.
    is_private = update.effective_chat is not None and update.effective_chat.type == "private"
    keyboard: list[list[InlineKeyboardButton]] = []

    lines = ["<b>Report</b>"]
    for r in rows:
        uname = html.escape(r["username"])
        lines.append(f"{r['icon']} <code>{r['user_id']}</code> {uname} · {r['detail']}")
        if is_private and base and r["uuid"]:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"{r['icon']} Open {r['user_id']}", web_app=WebAppInfo(url=f"{base}/report/{r['uuid']}")
                    )
                ]
            )
    if unknown:
        lines.append(f"❓ {len(unknown)} file(s) with no uploader on record: {html.escape(', '.join(unknown))}")
    lines.append("")
    lines.append(f"<i>{_LEGEND}</i>")

    markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    # Chunk on line boundaries to stay under Telegram's 4096 limit; the reply
    # markup rides on the final chunk.
    chunk = ""
    pending: list[str] = lines
    while pending:
        chunk = ""
        while pending and len(chunk) + len(pending[0]) + 1 <= 4000:
            chunk += pending.pop(0) + "\n"
        await update.message.reply_html(
            chunk,
            disable_web_page_preview=True,
            reply_markup=markup if not pending else None,
        )


async def start_report(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Create an encrypted report round for an already-resolved ``user_id``.

    Reusable seam: callers (the public ``/report`` command, or a deploy-side
    reply/#uid wrapper) resolve the target user id however they like, then hand
    it here for the file-gather → encrypt → DM flow.
    """
    assert update.message and update.effective_user

    status_msg = None
    with contextlib.suppress(Exception):
        status_msg = await update.message.reply_text("⏳ Preparing report…")
    on_progress = _progress_pump(status_msg, "⏳") if status_msg else None
    result = await asyncio.to_thread(prepare_report, user_id, on_progress)
    if status_msg is not None:
        with contextlib.suppress(Exception):
            await status_msg.delete()
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
        f"Encrypted <b>{result.encrypted}</b> file(s) and took them offline.\n\n"
        + f"<b>Image key (P1):</b> <code>{html.escape(result.p1 or '')}</code>\n\n"
        f"{launch}\n\n"
        f"<i>Use the global page password to open the report, then P1 to decrypt "
        f"the images. The files are no longer on disk — the encrypted blobs are "
        f"the only copy, so P1 is NOT recoverable and losing it loses the files. "
        f"Cancelling restores them to disk; filing keeps the reported ones "
        f"encrypted in the DB, bans the user, and deletes the rest.</i>",
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

    # web_app inline buttons only work in PRIVATE chats — offer the reports console
    # as a Mini App button there (signed initData), same as /report does per-report.
    is_private = update.effective_chat is not None and update.effective_chat.type == "private"
    markup = None
    if is_private and settings.REPORT_BASE_URL:
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Reports", web_app=WebAppInfo(url=f"{settings.REPORT_BASE_URL}/report/console"))]]
        )

    if menu_button_set:
        summary = "No reports on file yet." if not count else f"{count} report{'s' if count != 1 else ''} on file."
        await update.message.reply_html(
            f"{summary} Tap the <b>Reports</b> button below (or the menu button, bottom-left ⊞) to open the "
            "reports console (list, open a report, or create a new one).",
            reply_markup=markup,
        )
        return

    # Fallback when no menu button could be set (no REPORT_BASE_URL): give a link.
    url = f"{settings.REPORT_BASE_URL}/report/console" if settings.REPORT_BASE_URL else None
    if url:
        await update.message.reply_html(
            f"{count} report{'s' if count != 1 else ''} on file.",
            reply_markup=markup or InlineKeyboardMarkup([[InlineKeyboardButton("Open reports console", url=url)]]),
        )
    else:
        await update.message.reply_html(
            f"{count} report{'s' if count != 1 else ''} on file. (Reports console URL not configured.)"
        )
