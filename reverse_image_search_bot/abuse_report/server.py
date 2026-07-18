"""aiohttp report webview for the abuse-report pipeline.

Runs as a small server inside the RIS pod. The admin opens it as a Telegram Mini
App (menu button). Auth is two-layer:

1. **Telegram initData** — every API request carries the Mini App's signed
   ``initData``; we HMAC-verify it against the bot token and require the sender
   to be an admin. This proves the request came from an admin's Telegram session.
2. **Page password** — a single global password (same for every report, stored
   in Proton Pass as ``REPORT_PAGE_PASSWORD``), entered on the page and checked
   against the configured value.

The encrypted image blobs are served to the browser, which decrypts them locally
with the image key (P1) via WebCrypto — the server never returns plaintext for
display. Plaintext is only reconstructed server-side (from P1 supplied at submit)
to hand to NCMEC.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from reverse_image_search_bot import settings
from reverse_image_search_bot.abuse_report import crypto, ncmec
from reverse_image_search_bot.abuse_report.prepare import prepare_report, resolve_user
from reverse_image_search_bot.config import abuse

logger = logging.getLogger("abuse.server")

_STATIC = Path(__file__).parent / "static"
_VALID_CLASSES = {"A1", "A2", "B1", "B2"}


# --- initData validation ------------------------------------------------------


def verify_init_data(init_data: str, bot_token: str, max_age: int = 3600) -> dict | None:
    """Validate Telegram Mini App initData. Returns parsed user dict or None.

    Recipe: secret = HMAC_SHA256("WebAppData", bot_token); the check hash is
    HMAC_SHA256(secret, data_check_string) where data_check_string is the sorted
    "k=v\\n…" of all params except `hash`.
    """
    if not init_data:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    got_hash = pairs.pop("hash", None)
    if not got_hash:
        return None
    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, got_hash):
        return None
    # auth_date freshness
    try:
        import time

        if max_age and (time.time() - int(pairs.get("auth_date", "0"))) > max_age:
            return None
    except ValueError:
        return None
    try:
        return json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        return None


def _admin_from_request(request: web.Request) -> int | None:
    """Extract + verify the admin user id from initData (header or query)."""
    init_data = request.headers.get("X-Init-Data") or request.query.get("initData", "")
    user = verify_init_data(init_data, settings.TELEGRAM_API_TOKEN)
    if not user:
        return None
    uid = user.get("id")
    if uid not in settings.ADMIN_IDS:
        return None
    return uid


def _require_admin(request: web.Request) -> int:
    uid = _admin_from_request(request)
    if uid is None:
        raise web.HTTPUnauthorized(text="initData invalid or not an admin")
    return uid


def _report_or_404(uuid: str) -> dict:
    rep = abuse.get_report(uuid)
    if not rep:
        raise web.HTTPNotFound(text="report not found")
    return rep


def _require_page_secret(request: web.Request, rep: dict) -> None:
    """Page-password gate — a single global password (same for every report),
    supplied in the ``X-Page-Secret`` header, checked against the configured
    ``REPORT_PAGE_PASSWORD``. ``rep`` is unused now but kept for call-site parity.
    """
    entered = request.headers.get("X-Page-Secret", "")
    if not crypto.verify_global_page_password(entered, settings.REPORT_PAGE_PASSWORD):
        raise web.HTTPForbidden(text="page password incorrect")


# --- routes -------------------------------------------------------------------


async def reports_index(request: web.Request) -> web.StreamResponse:
    """Serve the reports-list Mini App shell. Auth happens via API calls."""
    return web.FileResponse(_STATIC / "reports.html")


async def api_reports_list(request: web.Request) -> web.Response:
    """List all reports (admin + global page password gated)."""
    _require_admin(request)
    if not crypto.verify_global_page_password(request.headers.get("X-Page-Secret", ""), settings.REPORT_PAGE_PASSWORD):
        raise web.HTTPForbidden(text="page password incorrect")
    reports = abuse.all_reports()
    return web.json_response(
        {
            "reports": [
                {
                    "uuid": r["report_uuid"],
                    "user_id": r["user_id"],
                    "username": r.get("username"),
                    "status": r["status"],
                    "ncmec_report_id": r["ncmec_report_id"],
                    "created_at": r["created_at"],
                }
                for r in reports
            ]
        }
    )


async def api_reports_create(request: web.Request) -> web.Response:
    """Create a new report from a target token (user id, @username, or filename).

    Returns the new report's uuid + the one-time image key (P1), which is shown
    once and never stored — the caller must surface it immediately.
    """
    _require_admin(request)
    if not crypto.verify_global_page_password(request.headers.get("X-Page-Secret", ""), settings.REPORT_PAGE_PASSWORD):
        raise web.HTTPForbidden(text="page password incorrect")
    admin_id = _admin_from_request(request)
    payload = await request.json()
    target = (payload.get("target") or "").strip()
    if not target:
        raise web.HTTPBadRequest(text="target (user id, @username, or filename) required")
    user_id = resolve_user(target)
    if user_id is None:
        raise web.HTTPNotFound(text=f"no uploader found for: {target}")

    result = prepare_report(user_id)
    if not result.ok:
        # An existing active report is a 409 carrying its uuid so the UI can jump to it.
        if result.existing_uuid:
            return web.json_response(
                {"ok": False, "error": result.error, "existing_uuid": result.existing_uuid}, status=409
            )
        raise web.HTTPBadRequest(text=result.error or "could not prepare report")

    # DM the requesting admin the one-time image key (P1) + launch link, so it is
    # delivered as a normal message (the page never shows P1 again after this).
    await _dm_report_created(request.app.get("bot"), admin_id, user_id, result)

    return web.json_response(
        {
            "ok": True,
            "uuid": result.report_uuid,
            "user_id": user_id,
            "p1": result.p1,
            "encrypted": result.encrypted,
        }
    )


async def _dm_report_created(bot, admin_id: int | None, user_id: int, result) -> None:
    """DM the admin the P1 image key + report link for an app-created report."""
    if bot is None or not admin_id:
        return
    import html as _html

    user = abuse.get_user(user_id) or {}
    uname = f"@{user['username']}" if user.get("username") else "—"
    url = f"{settings.REPORT_BASE_URL}/report/{result.report_uuid}" if settings.REPORT_BASE_URL else result.report_uuid
    try:
        await bot.send_message(
            admin_id,
            f"<b>Report prepared</b> for user <code>{user_id}</code> ({_html.escape(uname)})\n"
            f"Encrypted <b>{result.encrypted}</b> file(s).\n\n"
            f"<b>Image key (P1):</b> <code>{_html.escape(result.p1 or '')}</code>\n\n"
            f"Open it from the reports console, or: {_html.escape(url)}\n\n"
            f"<i>P1 is not stored — keep it to decrypt the images.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        logger.warning("failed to DM P1 for app-created report %s", result.report_uuid, exc_info=True)


async def index(request: web.Request) -> web.StreamResponse:
    """Serve the report page shell. UUID in path; auth happens via API calls."""
    uuid = request.match_info["uuid"]
    if not abuse.get_report(uuid):
        return web.Response(status=404, text="report not found")
    return web.FileResponse(_STATIC / "report.html")


async def api_unlock(request: web.Request) -> web.Response:
    """Verify P2 + return report metadata (user info, blob list). No ciphertext."""
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    _require_page_secret(request, rep)
    user = abuse.get_user(rep["user_id"]) or {}
    return web.json_response(
        {
            "uuid": rep["report_uuid"],
            "status": rep["status"],
            "status_detail": rep["status_detail"],
            "created_at": rep["created_at"],
            "ncmec_report_id": rep["ncmec_report_id"],
            "user": {
                "id": rep["user_id"],
                "username": user.get("username"),
                "first_name": user.get("first_name"),
                "last_name": user.get("last_name"),
                "banned_at": user.get("banned_at"),
            },
            "blobs": abuse.blob_meta(rep["report_uuid"]),
        }
    )


async def api_blob(request: web.Request) -> web.Response:
    """Return one encrypted blob (nonce + ciphertext) for in-browser decryption."""
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    _require_page_secret(request, rep)
    blob_id = int(request.match_info["blob_id"])
    row = abuse.get_blob_cipher(rep["report_uuid"], blob_id)
    if not row:
        raise web.HTTPNotFound(text="blob not found")
    body = bytes(row["nonce"]) + bytes(row["ciphertext"])
    return web.Response(body=body, content_type="application/octet-stream")


async def api_status(request: web.Request) -> web.Response:
    """Poll the report status (drives the live UI)."""
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    return web.json_response(
        {
            "status": rep["status"],
            "status_detail": rep["status_detail"],
            "ncmec_report_id": rep["ncmec_report_id"],
        }
    )


async def api_select(request: web.Request) -> web.Response:
    """Persist the admin's selection + per-image classification."""
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    _require_page_secret(request, rep)
    payload = await request.json()
    raw = payload.get("selections", {})
    selections: dict[int, str | None] = {}
    for k, v in raw.items():
        cls = v if v in _VALID_CLASSES else None
        selections[int(k)] = cls
    abuse.set_blob_selection(rep["report_uuid"], selections)
    return web.json_response({"ok": True, "selected": len(selections)})


async def api_submit(request: web.Request) -> web.Response:
    """Submit to NCMEC AND finish the report in one shot (irreversible).

    The console double-checks the selection in a client-side preview before this
    is called, so there is no separate review/finish step. Decrypt selected blobs
    with P1, upload + classify + finish, then delete the plaintext files from
    disk. The encrypted blobs are KEPT in the DB, linked to the finished report,
    so the files remain available for further inspection / law-enforcement.
    """
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    _require_page_secret(request, rep)
    payload = await request.json()
    p1 = payload.get("image_key", "")
    if not p1:
        raise web.HTTPBadRequest(text="image_key (P1) required")

    selected = abuse.report_blobs(rep["report_uuid"], selected_only=True)
    if not selected:
        raise web.HTTPBadRequest(text="no images selected")

    key = crypto.derive_key(p1)
    files = []
    for b in selected:
        try:
            plaintext = crypto.decrypt_file(bytes(b["nonce"]), bytes(b["ciphertext"]), key)
        except Exception as dec_err:
            raise web.HTTPBadRequest(text="image key (P1) incorrect — decryption failed") from dec_err
        if crypto.sha256_hex(plaintext) != b["plaintext_sha256"]:
            raise web.HTTPBadRequest(text="image key (P1) incorrect — hash mismatch")
        files.append({"plaintext": plaintext, "filename": b["saved_filename"], "classification": b["classification"]})

    incident_urls = [_public_file_url(b["saved_filename"]) for b in selected]
    abuse.set_report_status(rep["report_uuid"], abuse.REPORT_SUBMITTING)
    reported_user = abuse.get_user(rep["user_id"])
    source_chats = abuse.source_chats_for_user(rep["user_id"])
    try:
        report_id, _file_ids = await ncmec.submit_and_finish(
            files,
            incident_urls=incident_urls,
            reported_user=reported_user,
            source_chats=source_chats,
        )
    except ncmec.NcmecNotConfigured as e:
        abuse.set_report_status(rep["report_uuid"], abuse.REPORT_ERROR, str(e))
        raise web.HTTPServiceUnavailable(text=f"NCMEC not configured: {e}") from e
    except Exception as e:
        logger.exception("NCMEC submit+finish failed for report %s", rep["report_uuid"])
        abuse.set_report_status(rep["report_uuid"], abuse.REPORT_ERROR, str(e))
        raise web.HTTPBadGateway(text=f"NCMEC submit failed: {e}") from e

    abuse.set_report_ncmec_id(rep["report_uuid"], report_id)
    abuse.mark_report_filed(rep["report_uuid"])
    _cleanup_after_finish(rep)
    return web.json_response({"ok": True, "ncmec_report_id": report_id, "status": abuse.REPORT_FILED})


async def api_cancel(request: web.Request) -> web.Response:
    """Cancel the whole round (nothing filed with NCMEC).

    Cancelling means the user did nothing wrong, so we KEEP the user's original
    files on disk and the filename->user (files table) relation untouched. Only
    the report's encrypted blobs + the report row's status are affected.
    """
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    _require_page_secret(request, rep)
    abuse.set_report_status(rep["report_uuid"], abuse.REPORT_CANCELLED)
    # Blobs only — NOT the files table, NOT disk files.
    abuse.purge_report_blobs(rep["report_uuid"])
    return web.json_response({"ok": True, "status": abuse.REPORT_CANCELLED})


def _public_file_url(saved_filename: str) -> str:
    base = settings.UPLOADER.get("url", "").rstrip("/")
    return f"{base}/{saved_filename}" if base else saved_filename


def _cleanup_after_finish(rep: dict) -> None:
    """On finish: delete reported plaintext from disk + drop non-reported blobs.

    Retention rules:
    - The REPORTED (selected) files: their plaintext is deleted from disk, but
      their encrypted ``report_blobs`` are KEPT and stay linked to the filed
      report, so the material remains available for further inspection or a
      report to local law enforcement.
    - The NON-reported (unselected) files: the admin decided they are not part of
      the report, so their encrypted blobs are purged from the DB. Their
      plaintext on disk is left untouched (nothing was filed about them).

    The user row, ban, and report record are always kept.
    """
    reported = abuse.report_blobs(rep["report_uuid"], selected_only=True)
    upload_path = settings.UPLOADER.get("configuration", {}).get("path")
    if upload_path:
        for b in reported:
            try:
                fp = Path(upload_path) / b["saved_filename"]
                if fp.is_file():
                    fp.unlink()
            except Exception:
                logger.warning("failed to delete plaintext %s", b["saved_filename"], exc_info=True)
    # Drop only the non-reported blobs; keep the reported ones linked to the report.
    abuse.purge_unselected_blobs(rep["report_uuid"])


async def healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def build_app(bot=None) -> web.Application:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app["bot"] = bot  # PTB Bot for out-of-band DMs (report-created notification)
    app.router.add_get("/report/console", reports_index)
    app.router.add_get("/report/console/api/list", api_reports_list)
    app.router.add_post("/report/console/api/create", api_reports_create)
    app.router.add_get("/report/{uuid}", index)
    app.router.add_post("/report/{uuid}/api/unlock", api_unlock)
    app.router.add_get("/report/{uuid}/api/blob/{blob_id}", api_blob)
    app.router.add_get("/report/{uuid}/api/status", api_status)
    app.router.add_post("/report/{uuid}/api/select", api_select)
    app.router.add_post("/report/{uuid}/api/submit", api_submit)
    app.router.add_post("/report/{uuid}/api/cancel", api_cancel)
    app.router.add_get("/healthz", healthz)
    return app


async def start_report_server(bot=None) -> web.AppRunner | None:
    """Start the aiohttp server if enabled. Returns the runner (for shutdown)."""
    if not settings.REPORT_SERVER_ENABLED:
        logger.info("Report server disabled (REPORT_SERVER_ENABLED not set)")
        return None
    app = build_app(bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.REPORT_SERVER_HOST, settings.REPORT_SERVER_PORT)
    await site.start()
    logger.info("Report server listening on %s:%s", settings.REPORT_SERVER_HOST, settings.REPORT_SERVER_PORT)
    return runner
