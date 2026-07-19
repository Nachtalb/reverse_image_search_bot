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

    # 1) Any Cloudflare /f/<file> URLs present → treat the whole message as a bulk
    #    paste. 2) Otherwise a single target token (id / @username / filename).
    filenames = list(dict.fromkeys(_CF_FILE_RE.findall(body)))
    targets: list[tuple[int | None, str]] = []  # (user_id, source_label)
    unknown: list[str] = []

    if filenames:
        seen: set[int] = set()
        for fn in filenames:
            uid = abuse.find_user_by_filename(fn)
            if uid is None:
                unknown.append(fn)
            elif uid not in seen:
                seen.add(uid)
                targets.append((uid, fn))
    elif body:
        uid = resolve_user(body)
        if uid is None:
            await update.message.reply_text(f"No uploader found for: {body}")
            return
        targets.append((uid, body))
    else:
        await update.message.reply_text(
            "Usage: /report <user_id | @username | group/channel id | filename>\n"
            "or paste Cloudflare file URLs (https://ris.naa.gg/f/…) to report each uploader."
        )
        return

    # Prepare a report per unique target user via the shared summary helper.
    user_ids = [uid for uid, _ in targets if uid is not None]
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
    rows: list[dict] = []  # {icon, user_id, username, detail, uuid?}
    for uid in dict.fromkeys(user_ids):  # de-dup, preserve order
        user = abuse.get_user(uid) or {}
        uname = f"@{user['username']}" if user.get("username") else "—"
        result = prepare_report(uid)
        if result.ok:
            rows.append(
                {
                    "icon": "🆕",
                    "user_id": uid,
                    "username": uname,
                    "detail": f"P1 <code>{html.escape(result.p1 or '')}</code>",
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
