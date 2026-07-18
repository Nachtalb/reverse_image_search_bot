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
    """Submit to NCMEC: decrypt selected blobs with P1, upload + classify.

    The admin supplies P1 (image key) + NCMEC creds are server-side. This does
    submit -> upload -> file_info, then parks in 'review' for the final finish.
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
        report_id, _file_ids = await ncmec.submit_report(
            files,
            incident_urls=incident_urls,
            reported_user=reported_user,
            source_chats=source_chats,
        )
    except ncmec.NcmecNotConfigured as e:
        abuse.set_report_status(rep["report_uuid"], abuse.REPORT_ERROR, str(e))
        raise web.HTTPServiceUnavailable(text=f"NCMEC not configured: {e}") from e
    except Exception as e:
        logger.exception("NCMEC submit failed for report %s", rep["report_uuid"])
        abuse.set_report_status(rep["report_uuid"], abuse.REPORT_ERROR, str(e))
        raise web.HTTPBadGateway(text=f"NCMEC submit failed: {e}") from e

    abuse.set_report_ncmec_id(rep["report_uuid"], report_id)
    abuse.set_report_status(rep["report_uuid"], abuse.REPORT_REVIEW)
    return web.json_response({"ok": True, "ncmec_report_id": report_id, "status": abuse.REPORT_REVIEW})


async def api_finish(request: web.Request) -> web.Response:
    """Final finish: file the report with NCMEC (irreversible), then clean up."""
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    _require_page_secret(request, rep)
    if not rep["ncmec_report_id"]:
        raise web.HTTPBadRequest(text="report not submitted yet")
    try:
        await ncmec.finish_report(rep["ncmec_report_id"])
    except Exception as e:
        logger.exception("NCMEC finish failed for report %s", rep["report_uuid"])
        abuse.set_report_status(rep["report_uuid"], abuse.REPORT_ERROR, str(e))
        raise web.HTTPBadGateway(text=f"NCMEC finish failed: {e}") from e

    abuse.mark_report_filed(rep["report_uuid"])
    _cleanup_after_finish(rep)
    return web.json_response({"ok": True, "status": abuse.REPORT_FILED})


async def api_retract(request: web.Request) -> web.Response:
    """Retract the submitted (unfinished) NCMEC report, then clean up blobs."""
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    _require_page_secret(request, rep)
    if rep["ncmec_report_id"]:
        try:
            await ncmec.retract_report(rep["ncmec_report_id"])
        except Exception as e:
            logger.exception("NCMEC retract failed for report %s", rep["report_uuid"])
            abuse.set_report_status(rep["report_uuid"], abuse.REPORT_ERROR, str(e))
            raise web.HTTPBadGateway(text=f"NCMEC retract failed: {e}") from e
    abuse.set_report_status(rep["report_uuid"], abuse.REPORT_RETRACTED)
    abuse.purge_report_blobs(rep["report_uuid"])
    return web.json_response({"ok": True, "status": abuse.REPORT_RETRACTED})


async def api_cancel(request: web.Request) -> web.Response:
    """Cancel the whole round (before/without NCMEC).

    Distinct from retract: this is the top-level 'abandon this report' button. If
    the report was already submitted to NCMEC, retract it first.

    Cancelling means the user did nothing wrong, so we KEEP the user's original
    files on disk and the filename->user (files table) relation untouched. Only
    the report's encrypted blobs + the report row's status are affected. Disk
    deletion happens ONLY on finish (_cleanup_after_finish), never here.
    """
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    _require_page_secret(request, rep)
    if rep["ncmec_report_id"] and rep["status"] == abuse.REPORT_REVIEW:
        try:
            await ncmec.retract_report(rep["ncmec_report_id"])
        except Exception:
            logger.warning("retract during cancel failed for %s", rep["report_uuid"], exc_info=True)
    abuse.set_report_status(rep["report_uuid"], abuse.REPORT_CANCELLED)
    # Blobs only — NOT the files table, NOT disk files.
    abuse.purge_report_blobs(rep["report_uuid"])
    return web.json_response({"ok": True, "status": abuse.REPORT_CANCELLED})


def _public_file_url(saved_filename: str) -> str:
    base = settings.UPLOADER.get("url", "").rstrip("/")
    return f"{base}/{saved_filename}" if base else saved_filename


def _cleanup_after_finish(rep: dict) -> None:
    """On finish: purge encrypted blobs + delete plaintext files from disk.

    Keeps the user row, ban, and the report record. Files on the PVC named by
    saved_filename are removed.
    """
    blobs = abuse.report_blobs(rep["report_uuid"])
    upload_path = settings.UPLOADER.get("configuration", {}).get("path")
    if upload_path:
        for b in blobs:
            try:
                fp = Path(upload_path) / b["saved_filename"]
                if fp.is_file():
                    fp.unlink()
            except Exception:
                logger.warning("failed to delete plaintext %s", b["saved_filename"], exc_info=True)
    abuse.purge_report_blobs(rep["report_uuid"])


async def healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def build_app() -> web.Application:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app.router.add_get("/report/{uuid}", index)
    app.router.add_post("/report/{uuid}/api/unlock", api_unlock)
    app.router.add_get("/report/{uuid}/api/blob/{blob_id}", api_blob)
    app.router.add_get("/report/{uuid}/api/status", api_status)
    app.router.add_post("/report/{uuid}/api/select", api_select)
    app.router.add_post("/report/{uuid}/api/submit", api_submit)
    app.router.add_post("/report/{uuid}/api/finish", api_finish)
    app.router.add_post("/report/{uuid}/api/retract", api_retract)
    app.router.add_post("/report/{uuid}/api/cancel", api_cancel)
    app.router.add_get("/healthz", healthz)
    return app


async def start_report_server() -> web.AppRunner | None:
    """Start the aiohttp server if enabled. Returns the runner (for shutdown)."""
    if not settings.REPORT_SERVER_ENABLED:
        logger.info("Report server disabled (REPORT_SERVER_ENABLED not set)")
        return None
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.REPORT_SERVER_HOST, settings.REPORT_SERVER_PORT)
    await site.start()
    logger.info("Report server listening on %s:%s", settings.REPORT_SERVER_HOST, settings.REPORT_SERVER_PORT)
    return runner
