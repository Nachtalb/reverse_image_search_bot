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

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from reverse_image_search_bot import settings
from reverse_image_search_bot.abuse_report import crypto, ncmec
from reverse_image_search_bot.abuse_report import video as abuse_video
from reverse_image_search_bot.abuse_report.prepare import (
    blob_ciphertext,
    delete_user_files,
    prepare_report,
    purge_cipher_dir,
    resolve_targets,
    restore_report_files,
)
from reverse_image_search_bot.config import abuse

logger = logging.getLogger("abuse.server")

_STATIC = Path(__file__).parent / "static"
# Live prepare progress ("done/total"), keyed by the raw target token the create
# request was given (the client has no user id until create returns).
# Single process, so an in-memory dict is enough (same pattern as _submit_progress).
_prepare_progress: dict[str, str] = {}
# "NR" = selected/reported but Not Rated — no NCMEC industryClassification is
# sent (that field is optional). Everything else must be a real A1-B2 code.
_VALID_CLASSES = {"A1", "A2", "B1", "B2", "NR"}


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


def _no_cache(resp: web.StreamResponse) -> web.StreamResponse:
    """Stop the Telegram webview serving a stale copy of a Mini App page.

    The webview caches aggressively and has no reload button, so without this a
    deployed UI change is invisible until the cache happens to expire — it looks
    exactly like the fix was never shipped.
    """
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


async def reports_index(request: web.Request) -> web.StreamResponse:
    """Serve the reports-list Mini App shell. Auth happens via API calls."""
    return _no_cache(web.FileResponse(_STATIC / "reports.html"))


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
                    "display_name": " ".join(filter(None, (r.get("first_name"), r.get("last_name")))) or None,
                    "status": r["status"],
                    "ncmec_report_id": r["ncmec_report_id"],
                    "created_at": r["created_at"],
                }
                for r in reports
            ]
        }
    )


async def api_reports_stats(request: web.Request) -> web.Response:
    """Report records for the statistics dashboard (admin + pw gated).

    Returns the raw per-report records for every decided report (filed and
    deleted); the client does all aggregation and period filtering so year/month
    dropdowns switch instantly with no re-fetch.

    The query walks reports → users → sources → blobs → files. That is cheap on
    a warm page cache but takes ~2 s on a cold one (network block storage), so
    it runs off the event loop — otherwise the first stats open after a restart
    stalls the webhook and every other report request with it.
    """
    _require_admin(request)
    if not crypto.verify_global_page_password(request.headers.get("X-Page-Secret", ""), settings.REPORT_PAGE_PASSWORD):
        raise web.HTTPForbidden(text="page password incorrect")
    return web.json_response({"records": await asyncio.to_thread(abuse.report_stats)})


async def api_prepare_progress(request: web.Request) -> web.Response:
    """Live encryption progress for an in-flight create ("done/total").

    The create request itself blocks until the whole round is encrypted, so the
    console polls this alongside it to show movement on a big user/group.

    Keyed by the same ``target`` token the create was given — the client has no
    user id until the create returns, so it can't poll by id.
    """
    _require_admin(request)
    if not crypto.verify_global_page_password(request.headers.get("X-Page-Secret", ""), settings.REPORT_PAGE_PASSWORD):
        raise web.HTTPForbidden(text="page password incorrect")
    target = (request.query.get("target") or "").strip()
    if not target:
        raise web.HTTPBadRequest(text="target required")
    return web.json_response({"progress": _prepare_progress.get(target)})


async def api_reports_create(request: web.Request) -> web.Response:
    """Create report round(s) from a target field.

    The field takes any input shape: a user id, @username, filename, ``#uid``
    tag, or a whole pasted Cloudflare abuse report full of file URLs. Every
    token is resolved, deduped to unique uploaders, and one round is prepared
    per uploader. Returns one result entry per uploader (P1 shown once).
    """
    _require_admin(request)
    if not crypto.verify_global_page_password(request.headers.get("X-Page-Secret", ""), settings.REPORT_PAGE_PASSWORD):
        raise web.HTTPForbidden(text="page password incorrect")
    admin_id = _admin_from_request(request)
    payload = await request.json()
    target = (payload.get("target") or "").strip()
    if not target:
        raise web.HTTPBadRequest(text="target (user id, @username, filename, or file URLs) required")
    source = _source_or_400(payload.get("source") or abuse.DEFAULT_SOURCE)
    user_ids, unknown, indicators = resolve_targets(target)
    if not user_ids:
        raise web.HTTPNotFound(text=f"no uploader found for: {target}")

    results = []
    for user_id in user_ids:
        # prepare_report encrypts every file (PBKDF2 + AES) — run it off the
        # event loop so a big report can't stall the webhook/report server.
        # Progress is published under the target token so the console can poll
        # it while this request is still in flight.
        def note(done: int, total: int) -> None:
            _prepare_progress[target] = f"{done}/{total}"

        _prepare_progress[target] = "0/?"
        try:
            result = await asyncio.to_thread(prepare_report, user_id, note, indicators.get(user_id), source["id"])
        finally:
            _prepare_progress.pop(target, None)
        if result.ok:
            # DM the requesting admin the one-time image key (P1) + launch link,
            # so it is delivered as a normal message (the page never shows P1 again).
            await _dm_report_created(request.app.get("bot"), admin_id, user_id, result)
            results.append(
                {
                    "user_id": user_id,
                    "uuid": result.report_uuid,
                    "p1": result.p1,
                    "encrypted": result.encrypted,
                }
            )
        else:
            results.append(
                {
                    "user_id": user_id,
                    "error": result.error,
                    "existing_uuid": result.existing_uuid,
                    "filed_uuid": result.filed_uuid,
                    "ncmec_report_id": result.filed_ncmec_id,
                }
            )

    return web.json_response({"ok": True, "results": results, "unknown": unknown})


def _who(user_id: int) -> str:
    """Human label for a user: @username, else full name, else empty.

    Empty rather than a placeholder dash — every call site already shows the id,
    so a "—" would just be noise between it and the detail.
    """
    u = abuse.get_user(user_id) or {}
    if u.get("username"):
        return f"@{u['username']}"
    return " ".join(filter(None, (u.get("first_name"), u.get("last_name"))))


async def _dm_report_created(bot, admin_id: int | None, user_id: int, result, source: str | None = None) -> None:
    """DM the admin(s) the image key + report link for an app/API-created report."""
    if bot is None:
        return
    # An API-created report has no requesting admin — tell everyone.
    targets = [admin_id] if admin_id else list(settings.ADMIN_IDS)
    if not targets:
        return
    import html as _html

    url = f"{settings.REPORT_BASE_URL}/report/console" if settings.REPORT_BASE_URL else ""
    via = f" · via {_html.escape(source)}" if source else ""
    for target in targets:
        try:
            await bot.send_message(
                target,
                f"🆕 <code>{user_id}</code> {_html.escape(_who(user_id))} · {result.encrypted} file(s){via}\n"
                f"Image key: <code>{_html.escape(result.p1 or '')}</code>",
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=(
                    InlineKeyboardMarkup([[InlineKeyboardButton("Reports", web_app=WebAppInfo(url=url))]])
                    if url
                    else None
                ),
            )
        except Exception:
            logger.warning("failed to DM the image key for app-created report %s", result.report_uuid, exc_info=True)


# --- sources + API keys (console management) ----------------------------------


def _source_or_400(name: str) -> dict:
    """Resolve a source name to its row. A source must exist before it is used."""
    source = abuse.get_source_by_name(name.strip())
    if not source:
        raise web.HTTPBadRequest(text=f"unknown source: {name} — create it first")
    return source


async def api_sources(request: web.Request) -> web.Response:
    """List / create / delete report sources (admin + page password gated)."""
    _require_admin(request)
    if not crypto.verify_global_page_password(request.headers.get("X-Page-Secret", ""), settings.REPORT_PAGE_PASSWORD):
        raise web.HTTPForbidden(text="page password incorrect")
    if request.method == "POST":
        payload = await request.json()
        action = payload.get("action")
        if action == "add":
            name = (payload.get("name") or "").strip()
            if not name:
                raise web.HTTPBadRequest(text="name required")
            if abuse.get_source_by_name(name):
                raise web.HTTPBadRequest(text=f"source {name} already exists")
            abuse.add_source(name)
        elif action == "delete":
            err = abuse.delete_source(int(payload.get("id") or 0))
            if err:
                raise web.HTTPBadRequest(text=err)
        else:
            raise web.HTTPBadRequest(text="action must be add or delete")
    return web.json_response({"sources": abuse.list_sources(), "default": abuse.DEFAULT_SOURCE})


async def api_keys(request: web.Request) -> web.Response:
    """List / create / rotate / delete ingest API keys.

    The key itself is returned exactly once — on ``add`` and on ``rotate``.
    Every listing returns the server-side mask, never the secret.
    """
    _require_admin(request)
    if not crypto.verify_global_page_password(request.headers.get("X-Page-Secret", ""), settings.REPORT_PAGE_PASSWORD):
        raise web.HTTPForbidden(text="page password incorrect")
    new_key = None
    if request.method == "POST":
        payload = await request.json()
        action = payload.get("action")
        if action in ("add", "rotate"):
            new_key = crypto.gen_api_key()
            key_hash, preview = crypto.hash_api_key(new_key), crypto.mask_api_key(new_key)
            if action == "add":
                name = (payload.get("name") or "").strip()
                if not name:
                    raise web.HTTPBadRequest(text="name required")
                abuse.add_api_key(name, key_hash, preview)
            elif not abuse.rotate_api_key(int(payload.get("id") or 0), key_hash, preview):
                raise web.HTTPNotFound(text="key not found")
        elif action == "delete":
            if not abuse.delete_api_key(int(payload.get("id") or 0)):
                raise web.HTTPNotFound(text="key not found")
        else:
            raise web.HTTPBadRequest(text="action must be add, rotate or delete")
    return web.json_response({"keys": abuse.list_api_keys(), "new_key": new_key})


# --- ingest API ---------------------------------------------------------------


async def _require_api_key(request: web.Request) -> dict:
    """Bearer-token auth for the machine ingest endpoint (no initData, no page pw).

    The lookup hash is a PBKDF2 derivation, so it runs off the event loop — an
    automated caller can hammer this endpoint.
    """
    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    key = await asyncio.to_thread(_lookup_api_key, token) if token else None
    if not key:
        raise web.HTTPUnauthorized(text="invalid or missing API key")
    return key


def _lookup_api_key(token: str) -> dict | None:
    return abuse.api_key_by_hash(crypto.hash_api_key(token))


async def api_ingest(request: web.Request) -> web.Response:
    """Create report rounds from an automated feed.

    ``{"source": "cloudflare-csam", "targets": ["123", "@name", "<pasted urls>"]}``
    — every target goes through the same resolve+prepare path as ``/report`` and
    the console. The one-time image key is NEVER returned here; it is DM'd to the
    admins exactly as for a manually-created report.
    """
    await _require_api_key(request)
    payload = await request.json()
    source = _source_or_400(payload.get("source") or "")
    targets = payload.get("targets")
    if isinstance(targets, str):
        targets = [targets]
    if not targets or not isinstance(targets, list):
        raise web.HTTPBadRequest(text="targets (list of user ids, @usernames, filenames or URLs) required")

    user_ids, unknown, indicators = resolve_targets("\n".join(str(t) for t in targets))
    results = []
    for user_id in user_ids:
        result = await asyncio.to_thread(prepare_report, user_id, None, indicators.get(user_id), source["id"])
        if result.ok:
            await _dm_report_created(request.app.get("bot"), None, user_id, result, source["name"])
            results.append({"user_id": user_id, "uuid": result.report_uuid, "encrypted": result.encrypted})
        else:
            results.append(
                {
                    "user_id": user_id,
                    "error": result.error,
                    "existing_uuid": result.existing_uuid,
                    "filed_uuid": result.filed_uuid,
                    "ncmec_report_id": result.filed_ncmec_id,
                }
            )
    return web.json_response({"ok": True, "source": source["name"], "results": results, "unknown": unknown})


async def index(request: web.Request) -> web.StreamResponse:
    """Serve the report page shell. UUID in path; auth happens via API calls."""
    uuid = request.match_info["uuid"]
    if not abuse.get_report(uuid):
        return web.Response(status=404, text="report not found")
    return _no_cache(web.FileResponse(_STATIC / "report.html"))


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
                "language_code": user.get("language_code"),
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
    ct = blob_ciphertext(row)
    if ct is None:
        raise web.HTTPNotFound(text="ciphertext missing on disk")
    body = bytes(row["nonce"]) + ct
    return web.Response(body=body, content_type="application/octet-stream")


async def api_fetch_video(request: web.Request) -> web.Response:
    """Lazily download + encrypt-to-disk the ORIGINAL video for a blob.

    Best-effort: needs P1 (to encrypt with the report key) and the bot handle.
    On success the blob gains a video; the browser can then GET the video blob
    and decrypt it locally. Failures return ``ok:false`` + a human reason
    (deleted message, over 20 MB, not a video, …) — never a 500.
    """
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    _require_page_secret(request, rep)
    payload = await request.json()
    p1 = payload.get("image_key", "")
    if not p1:
        raise web.HTTPBadRequest(text="image key required")
    blob = abuse.get_report_blob(int(request.match_info["blob_id"]))
    if not blob or blob["report_uuid"] != rep["report_uuid"]:
        raise web.HTTPNotFound(text="blob not found")

    bot = request.app.get("bot")
    if bot is None:
        raise web.HTTPServiceUnavailable(text="bot unavailable for video fetch")
    res = await abuse_video.fetch_and_encrypt_video(bot, blob, p1)
    return web.json_response({"ok": res.ok, "reason": res.reason, "video_filename": res.filename})


async def api_video(request: web.Request) -> web.Response:
    """Return a blob's encrypted video (nonce + ciphertext from disk)."""
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    _require_page_secret(request, rep)
    blob = abuse.get_report_blob(int(request.match_info["blob_id"]))
    if not blob or blob["report_uuid"] != rep["report_uuid"] or not blob.get("video_path"):
        raise web.HTTPNotFound(text="no video for this blob")
    base = settings.UPLOADER.get("configuration", {}).get("path")
    fp = Path(base) / blob["video_path"] if base else None
    if not fp or not fp.is_file():
        raise web.HTTPNotFound(text="video ciphertext missing on disk")
    body = bytes(blob["video_nonce"]) + fp.read_bytes()
    return web.Response(body=body, content_type="application/octet-stream")


async def api_status(request: web.Request) -> web.Response:
    """Poll the report status (drives the live UI).

    While a background submit runs (status ``submitting``) ``progress`` carries
    a short human-readable step string, e.g. "uploading video 3/7".
    """
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    return web.json_response(
        {
            "status": rep["status"],
            "status_detail": rep["status_detail"],
            "ncmec_report_id": rep["ncmec_report_id"],
            "progress": _submit_progress.get(rep["report_uuid"]),
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
    # DB write may wait on the write lock (busy_timeout) — keep it off the event loop.
    await asyncio.to_thread(abuse.set_blob_selection, rep["report_uuid"], selections)
    return web.json_response({"ok": True, "selected": len(selections)})


def _epoch_to_dt(ts: int | None) -> datetime | None:
    """Convert a stored epoch-seconds int to a tz-aware UTC datetime (or None)."""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=UTC)
    except ValueError, OverflowError, OSError:
        return None


def _incident_date(files: list[dict]) -> datetime | None:
    """Earliest upload time across the reported files (the incident time)."""
    times = [f["upload_time"] for f in files if f.get("upload_time")]
    return min(times) if times else None


def _chat_room_name(request: web.Request, rep: dict, source_chats: list[dict] | None) -> str | None:
    """Short label for where the media was sent (the chat incident 'room').

    A group/channel upload names that chat; otherwise it was a DM to the bot, so
    name the bot itself.
    """
    for c in source_chats or []:
        label = c.get("title") or (f"@{c['username']}" if c.get("username") else str(c.get("chat_id")))
        return f"{c.get('chat_type', 'chat')}: {label}"
    bot = request.app.get("bot")
    uname = getattr(bot, "username", None) if bot is not None else None
    return f"@{uname} (bot DM)" if uname else "bot DM"


async def _fetch_and_store_bio(request: web.Request, user_id: int) -> None:
    """Best-effort: fetch the reported user's Telegram bio and store it.

    Uses get_chat on the user id (a private chat exists because they DMed the
    bot). Silent on any failure — bio is a nice-to-have, never blocks a report.
    """
    bot = request.app.get("bot")
    if bot is None:
        return
    try:
        chat = await bot.get_chat(user_id)
        bio = getattr(chat, "bio", None)
        if bio:
            abuse.set_user_bio(user_id, bio)
    except Exception:
        logger.info("could not fetch bio for user %s", user_id, exc_info=True)


async def _gather_selected_files(
    request: web.Request, rep: dict, p1: str, progress: Callable[[str], None] | None = None
) -> tuple[list[dict], list[dict]]:
    """Decrypt every selected blob (frame + any source video) with P1.

    Shared by the review preview AND the live submit so both operate on the exact
    same file set. Ensures every selected video is fetched first (best-effort),
    then returns ``(files, selected_blobs)`` where ``files`` is the list of
    per-file dicts handed to the NCMEC builders. Each file dict carries a ``kind``
    ("frame" | "video"), its ``blob_id``, the file's ``upload_time`` and any
    ``caption`` so the UI can pair them up and the builders can fill the fields.

    ``progress`` (optional) receives short human-readable step strings — the
    async submit path forwards them to the polling UI.
    """

    def _note(msg: str) -> None:
        if progress is not None:
            progress(msg)

    selected = abuse.report_blobs(rep["report_uuid"], selected_only=True)
    if not selected:
        raise web.HTTPBadRequest(text="no images selected")

    # Ensure EVERY selected video is fetched — not just the ones the admin opened
    # in the viewer. Any selected blob whose upload was a video but has no video
    # yet is lazily fetched now (best-effort; failures degrade to frame-only).
    bot = request.app.get("bot")
    if bot is not None:
        pending = [b for b in selected if not b.get("video_path")]
        for i, b in enumerate(pending, 1):
            _note(f"fetching source video {i}/{len(pending)}")
            await abuse_video.fetch_and_encrypt_video(bot, b, p1)
        # Re-read so the freshly-fetched video columns are visible below.
        selected = abuse.report_blobs(rep["report_uuid"], selected_only=True)

    key = crypto.derive_key(p1)
    files: list[dict] = []
    base = settings.UPLOADER.get("configuration", {}).get("path")
    for idx, b in enumerate(selected, 1):
        _note(f"decrypting {idx}/{len(selected)}")
        cipher = blob_ciphertext(b)
        if cipher is None:
            raise web.HTTPBadRequest(text=f"ciphertext missing on disk for {b['saved_filename']}")
        try:
            plaintext = crypto.decrypt_file(bytes(b["nonce"]), cipher, key)
        except Exception as dec_err:
            raise web.HTTPBadRequest(text="image key incorrect — decryption failed") from dec_err
        if crypto.sha256_hex(plaintext) != b["plaintext_sha256"]:
            raise web.HTTPBadRequest(text="image key incorrect — hash mismatch")
        # Report the extracted frame/still. original_file_name keeps the
        # uploader's original name when we have one (important to preserve);
        # location_of_file is our PUBLIC copy's URL (the one that may have been
        # used on the web). Two distinct facts in their two distinct NCMEC fields.
        frec = abuse.file_by_unique_id(b["file_unique_id"]) or {}
        upload_dt = _epoch_to_dt(frec.get("upload_time"))
        caption = frec.get("caption")
        files.append(
            {
                # "frame" only when this still was extracted from a real source
                # video; a standalone image (e.g. a jpg) is just an "image".
                "kind": "frame" if frec.get("is_video") else "image",
                "blob_id": b["id"],
                "plaintext": plaintext,
                "filename": frec.get("original_filename") or b["saved_filename"],
                "location": _public_file_url(b["saved_filename"]),
                "classification": b["classification"],
                "upload_time": upload_dt,
                "caption": caption,
            }
        )
        # If this blob has a source video, report it TOO (same classification).
        # The video is only stored encrypted, never served publicly, so it has an
        # original filename but no public location.
        if b.get("video_path") and base:
            vfp = Path(base) / b["video_path"]
            if vfp.is_file():
                try:
                    vplain = crypto.decrypt_file(bytes(b["video_nonce"]), vfp.read_bytes(), key)
                except Exception as verr:
                    raise web.HTTPBadRequest(text="image key incorrect — video decryption failed") from verr
                if crypto.sha256_hex(vplain) != b["video_sha256"]:
                    raise web.HTTPBadRequest(text="image key incorrect — video hash mismatch")
                files.append(
                    {
                        "kind": "video",
                        "blob_id": b["id"],
                        "plaintext": vplain,
                        "filename": b["video_filename"] or b["saved_filename"],
                        "classification": b["classification"],
                        "upload_time": upload_dt,
                        "caption": caption,
                    }
                )
    return files, selected


async def api_review(request: web.Request) -> web.Response:
    """Build the EXACT NCMEC payload for the current selection, without filing.

    Decrypts the selected frames + source videos with P1, runs the same NCMEC
    builders the live submit uses, and returns the resulting objects as JSON so
    the review dialog can show everything that will be sent — reporter, reported
    person, incident, and every file (frame AND video) with its hash + fields.
    Nothing is uploaded; nothing is filed.
    """
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    _require_page_secret(request, rep)
    payload = await request.json()
    p1 = payload.get("image_key", "")
    if not p1:
        raise web.HTTPBadRequest(text="image key required")

    files, selected = await _gather_selected_files(request, rep, p1)
    # Fetch the reported user's bio (best-effort) before reading the row, so it
    # shows up in the review exactly as it will be sent.
    await _fetch_and_store_bio(request, rep["user_id"])
    incident_urls = [_public_file_url(b["saved_filename"]) for b in selected]
    reported_user = abuse.get_user(rep["user_id"])
    source_chats = abuse.source_chats_for_user(rep["user_id"])
    ncmec_payload = ncmec.preview_payload(
        files,
        incident_urls=incident_urls,
        reported_user=reported_user,
        source_chats=source_chats,
        incident_date=_incident_date(files),
        chat_room_name=_chat_room_name(request, rep, source_chats),
    )
    # Per-file summary the UI pairs with its thumbnails/videos (no plaintext).
    file_summary = [
        {
            "kind": f["kind"],
            "blob_id": f["blob_id"],
            "filename": f["filename"],
            "location": f.get("location"),
            "classification": f["classification"],
            "hashes": ncmec_payload["files"][i].get("original_file_hash"),
            "size_bytes": len(f["plaintext"]),
        }
        for i, f in enumerate(files)
    ]
    return web.json_response(
        {
            "ncmec_configured": bool(settings.NCMEC_USERNAME and settings.NCMEC_PASSWORD),
            "reporter": ncmec_payload["report"].get("reporter"),
            "reported": ncmec_payload["report"].get("person_or_user_reported"),
            "incident": ncmec_payload["report"].get("incident_summary"),
            "internet_details": ncmec_payload["report"].get("internet_details"),
            "files": file_summary,
            "file_details": ncmec_payload["files"],
            "raw_report": ncmec_payload["report"],
        }
    )


async def api_submit(request: web.Request) -> web.Response:
    """Kick off the NCMEC submit+finish in the background (irreversible).

    The full pipeline (fetch remaining videos, decrypt, upload everything,
    finish) can take minutes — far past Cloudflare's ~100 s proxy timeout — so
    this returns immediately and the page polls ``/api/status``, which carries
    a live ``progress`` string while status is ``submitting``. The console
    double-checks the selection in a client-side preview before calling this.
    On success the encrypted blobs are KEPT in the DB, linked to the finished
    report, so the files remain available for inspection / law-enforcement.
    """
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    _require_page_secret(request, rep)
    payload = await request.json()
    p1 = payload.get("image_key", "")
    if not p1:
        raise web.HTTPBadRequest(text="image key required")
    uuid = rep["report_uuid"]
    if uuid in _submit_tasks and not _submit_tasks[uuid].done():
        return web.json_response({"ok": True, "status": abuse.REPORT_SUBMITTING})  # already running

    abuse.set_report_status(uuid, abuse.REPORT_SUBMITTING)
    _submit_progress[uuid] = "starting"
    task = asyncio.create_task(_run_submit(request, rep, p1))
    _submit_tasks[uuid] = task
    task.add_done_callback(lambda _t: _submit_tasks.pop(uuid, None))
    return web.json_response({"ok": True, "status": abuse.REPORT_SUBMITTING})


# Live submit state, keyed by report_uuid (single process — in-memory is fine).
_submit_tasks: dict[str, asyncio.Task] = {}
_submit_progress: dict[str, str] = {}


async def _run_submit(request: web.Request, rep: dict, p1: str) -> None:
    """The actual submit+finish pipeline, run as a background task."""
    uuid = rep["report_uuid"]

    def note(msg: str) -> None:
        _submit_progress[uuid] = msg
        logger.info("submit %s: %s", uuid, msg)

    try:
        files, selected = await _gather_selected_files(request, rep, p1, progress=note)
        incident_urls = [_public_file_url(b["saved_filename"]) for b in selected]
        await _fetch_and_store_bio(request, rep["user_id"])
        reported_user = abuse.get_user(rep["user_id"])
        source_chats = abuse.source_chats_for_user(rep["user_id"])
        report_id, _file_ids = await ncmec.submit_and_finish(
            files,
            incident_urls=incident_urls,
            reported_user=reported_user,
            source_chats=source_chats,
            incident_date=_incident_date(files),
            chat_room_name=_chat_room_name(request, rep, source_chats),
            progress=note,
        )
    except web.HTTPException as e:
        # _gather_selected_files raises HTTP errors (bad key, no selection).
        abuse.set_report_status(uuid, abuse.REPORT_ERROR, e.text or e.reason)
        return
    except Exception as e:
        logger.exception("NCMEC submit+finish failed for report %s", uuid)
        abuse.set_report_status(uuid, abuse.REPORT_ERROR, str(e))
        return
    finally:
        _submit_progress.pop(uuid, None)

    abuse.set_report_ncmec_id(uuid, report_id)
    abuse.mark_report_filed(uuid)
    # Filing IS the decision: every file in the round the admin did NOT select is
    # thereby cleared (not problematic) and excluded from future reports.
    unselected = [b["file_unique_id"] for b in abuse.report_blobs(uuid) if not b["selected"]]
    abuse.set_files_cleared(unselected)
    _cleanup_after_finish(rep)
    _ban_reported_user(request.app.get("bot_data"), rep["user_id"])


async def api_cancel(request: web.Request) -> web.Response:
    """Cancel the whole round (nothing filed with NCMEC).

    Cancelling means the user did nothing wrong, so every file taken offline when
    the report was prepared is DECRYPTED BACK ONTO DISK — requiring P1, since the
    plaintext only exists inside the blobs now. The filename->user (files table)
    relation is untouched; only the encrypted blobs and the report status change.

    Optional ``clear_files`` in the JSON body additionally marks every file in
    the round as cleared (not problematic) — excluded from future reports.
    """
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    _require_page_secret(request, rep)
    payload = {}
    with contextlib.suppress(Exception):
        payload = await request.json()
    p1 = payload.get("image_key", "")
    if not p1:
        raise web.HTTPBadRequest(text="image key required to restore the files")
    # Restore BEFORE purging the blobs — they are the only copy of the plaintext.
    # A wrong key aborts without writing anything, so the files stay recoverable.
    err = await asyncio.to_thread(restore_report_files, rep["report_uuid"], p1)
    if err:
        raise web.HTTPBadRequest(text=err)
    # `is True` (not truthiness) so a missing/odd body can never clear files.
    clear_files = payload.get("clear_files") is True
    if clear_files:
        abuse.set_files_cleared([b["file_unique_id"] for b in abuse.report_blobs(rep["report_uuid"])])
    abuse.set_report_status(rep["report_uuid"], abuse.REPORT_CANCELLED)
    # Delete any encrypted video ciphertext on disk, then purge blobs (DB only —
    # NOT the files table, NOT the user's original disk files).
    base = settings.UPLOADER.get("configuration", {}).get("path")
    if base:
        for b in abuse.report_blobs(rep["report_uuid"]):
            if b.get("video_path"):
                try:
                    vfp = Path(base) / b["video_path"]
                    if vfp.is_file():
                        vfp.unlink()
                except Exception:
                    logger.warning("failed to delete video on cancel %s", b["video_path"], exc_info=True)
    abuse.purge_report_blobs(rep["report_uuid"])
    purge_cipher_dir(rep["report_uuid"])
    return web.json_response({"ok": True, "status": abuse.REPORT_CANCELLED})


async def api_delete(request: web.Request) -> web.Response:
    """Destroy the SELECTED files and put the rest back online. Nothing is filed.

    For material that is plainly unwanted but can't be attributed to a minor —
    a Cloudflare complaint about content nobody can age-verify. Deleting it is
    the right call; banning the uploader and filing with NCMEC is not.

    The selected blobs' plaintext is never written back (their ciphertext and
    rows are dropped with the round), every other file is restored to disk, and
    the report is closed as ``deleted``. The uploader is NOT banned. Deleted
    files are marked cleared so a later round doesn't drag them back in.
    """
    _require_admin(request)
    rep = _report_or_404(request.match_info["uuid"])
    _require_page_secret(request, rep)
    payload = await request.json()
    p1 = payload.get("image_key", "")
    if not p1:
        raise web.HTTPBadRequest(text="image key required")
    doomed = [b for b in abuse.report_blobs(rep["report_uuid"]) if b["selected"]]
    if not doomed:
        raise web.HTTPBadRequest(text="select the files to delete first")
    # Restore everything EXCEPT the doomed files. This verifies the key against
    # every blob before writing or deleting anything, so a wrong key destroys
    # nothing.
    err = await asyncio.to_thread(restore_report_files, rep["report_uuid"], p1, {b["id"] for b in doomed})
    if err:
        raise web.HTTPBadRequest(text=err)
    # The deleted files must not come back in a future round for this user.
    abuse.set_files_cleared([b["file_unique_id"] for b in doomed])
    abuse.set_report_status(rep["report_uuid"], abuse.REPORT_DELETED, detail=f"{len(doomed)} file(s) deleted")
    base = settings.UPLOADER.get("configuration", {}).get("path")
    if base:
        for b in abuse.report_blobs(rep["report_uuid"]):
            if b.get("video_path"):
                try:
                    vfp = Path(base) / b["video_path"]
                    if vfp.is_file():
                        vfp.unlink()
                except Exception:
                    logger.warning("failed to delete video on delete %s", b["video_path"], exc_info=True)
    abuse.purge_report_blobs(rep["report_uuid"])
    purge_cipher_dir(rep["report_uuid"])
    return web.json_response({"ok": True, "status": abuse.REPORT_DELETED, "deleted": len(doomed)})


def _public_file_url(saved_filename: str) -> str:
    base = settings.UPLOADER.get("url", "").rstrip("/")
    return f"{base}/{saved_filename}" if base else saved_filename


def _ban_reported_user(bot_data, user_id: int) -> None:
    """Ban the reported uploader on filing: DB + live in-memory list.

    Mirrors /ban's dual-write so the ban takes effect immediately without a
    restart. ``set_banned`` is the durable record (survives a cleared pickle,
    restored on the next startup sync); appending to ``bot_data['banned_users']``
    is what the live search handler actually checks. ``bot_data`` may be None in
    tests / when the server runs bot-less — the DB write still happens.

    A ban also deletes everything the user still has on disk (anything uploaded
    after this round was prepared): banned means nothing of theirs stays served.
    """
    try:
        abuse.set_banned(user_id, True)
    except Exception:
        logger.warning("failed to set DB ban for reported user %s", user_id, exc_info=True)
    delete_user_files(user_id)
    if bot_data is None:
        return
    try:
        banned = bot_data.setdefault("banned_users", [])
        if user_id not in banned:
            banned.append(user_id)
    except Exception:
        logger.warning("failed to live-ban reported user %s", user_id, exc_info=True)


def _cleanup_after_finish(rep: dict) -> None:
    """On finish: move the reported ciphertext INTO the DB, drop everything else.

    Retention rules:
    - The REPORTED (selected) files: filing is what earns a place in the DB, so
      their encrypted bytes are read off disk and written into the blob row.
      They stay linked to the filed report, available for further inspection or
      a report to local law enforcement, and no longer depend on a file that the
      ban sweep below would delete. Their plaintext left the disk at prepare time.
    - Everything else in the round: purged. The unselected blobs are deleted
      from the DB, and the report's whole on-disk ciphertext directory goes with
      them — filing means the user is banned, and a banned user's material is
      not kept. Reported VIDEOS keep their encrypted file on disk (they are far
      too large for SQLite; that is the pre-existing design).

    The user row, ban, and report record are always kept.
    """
    upload_path = settings.UPLOADER.get("configuration", {}).get("path")
    # Reported images: disk ciphertext -> DB. Do this BEFORE any purging.
    for b in abuse.report_blobs(rep["report_uuid"], selected_only=True):
        if not b.get("cipher_path"):
            continue
        cipher = blob_ciphertext(b)
        if cipher is None:
            logger.warning("ciphertext missing for filed blob %s — cannot persist", b["id"])
            continue
        abuse.set_blob_ciphertext(b["id"], cipher)
    if upload_path:
        # Delete encrypted video ciphertext for UNSELECTED blobs (their blobs are
        # about to be purged); reported blobs keep their encrypted video on disk.
        for b in abuse.report_blobs(rep["report_uuid"]):
            if not b["selected"] and b.get("video_path"):
                try:
                    vfp = Path(upload_path) / b["video_path"]
                    if vfp.is_file():
                        vfp.unlink()
                except Exception:
                    logger.warning("failed to delete unselected video %s", b["video_path"], exc_info=True)
    # Drop only the non-reported blobs; keep the reported ones linked to the report.
    abuse.purge_unselected_blobs(rep["report_uuid"])
    # Every image ciphertext is either in the DB now (reported) or unwanted.
    purge_cipher_dir(rep["report_uuid"])


async def healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def build_app(bot=None, bot_data=None) -> web.Application:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app["bot"] = bot  # PTB Bot for out-of-band DMs (report-created notification)
    # The live Application.bot_data dict — same object handlers read via
    # context.bot_data. Lets the report server live-ban a user on filing (append
    # to banned_users) with no restart, matching /ban's dual-write.
    app["bot_data"] = bot_data
    app.router.add_get("/report/console", reports_index)
    app.router.add_get("/report/console/api/list", api_reports_list)
    app.router.add_get("/report/console/api/stats", api_reports_stats)
    app.router.add_get("/report/console/api/prepare_progress", api_prepare_progress)
    app.router.add_post("/report/console/api/create", api_reports_create)
    app.router.add_route("*", "/report/console/api/sources", api_sources)
    app.router.add_route("*", "/report/console/api/keys", api_keys)
    app.router.add_post("/report/api/ingest", api_ingest)
    app.router.add_get("/report/{uuid}", index)
    app.router.add_post("/report/{uuid}/api/unlock", api_unlock)
    app.router.add_get("/report/{uuid}/api/blob/{blob_id}", api_blob)
    app.router.add_post("/report/{uuid}/api/blob/{blob_id}/fetch_video", api_fetch_video)
    app.router.add_get("/report/{uuid}/api/blob/{blob_id}/video", api_video)
    app.router.add_get("/report/{uuid}/api/status", api_status)
    app.router.add_post("/report/{uuid}/api/select", api_select)
    app.router.add_post("/report/{uuid}/api/review", api_review)
    app.router.add_post("/report/{uuid}/api/submit", api_submit)
    app.router.add_post("/report/{uuid}/api/cancel", api_cancel)
    app.router.add_post("/report/{uuid}/api/delete", api_delete)
    app.router.add_get("/healthz", healthz)
    return app


async def start_report_server(bot=None, bot_data=None) -> web.AppRunner | None:
    """Start the aiohttp server if enabled. Returns the runner (for shutdown)."""
    if not settings.REPORT_SERVER_ENABLED:
        logger.info("Report server disabled (REPORT_SERVER_ENABLED not set)")
        return None
    app = build_app(bot=bot, bot_data=bot_data)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.REPORT_SERVER_HOST, settings.REPORT_SERVER_PORT)
    await site.start()
    logger.info("Report server listening on %s:%s", settings.REPORT_SERVER_HOST, settings.REPORT_SERVER_PORT)
    return runner
