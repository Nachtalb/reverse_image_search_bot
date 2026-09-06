"""HTTP API for the user-facing search-history Mini App.

Every route authenticates from the Telegram initData signature and scopes each
query to the caller's own user id. A user id is NEVER read from a query
parameter — that would let anyone page through someone else's history.

Routes are registered on the same aiohttp app as the admin report console (see
``abuse_report/server.py``), which is why the module only exports ``add_routes``.
"""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from reverse_image_search_bot import settings
from reverse_image_search_bot.config import abuse
from reverse_image_search_bot.i18n import t
from reverse_image_search_bot.utils.telegram_auth import verify_init_data
from reverse_image_search_bot.webapp import thumbs

logger = logging.getLogger("webapp.history")

_STATIC = __import__("pathlib").Path(__file__).parent / "static"

PAGE_SIZE = 20
MAX_PAGE_SIZE = 50

# The strings the page needs. Kept explicit rather than shipping the whole
# catalogue: the app should not hand a client the bot's entire i18n table.
_UI_KEYS = (
    "app.title",
    "app.empty",
    "app.empty_hint",
    "app.no_results",
    "app.legacy_entry",
    "app.open",
    "app.delete",
    "app.delete_confirm",
    "app.search_again",
    "app.search_again_sent",
    "app.loading",
    "app.error",
)


def _user_from_request(request: web.Request) -> dict | None:
    """The verified Telegram user behind this request, or None."""
    init_data = request.headers.get("X-Init-Data") or request.query.get("initData", "")
    return verify_init_data(init_data, settings.TELEGRAM_API_TOKEN)


def _require_user(request: web.Request) -> int:
    user = _user_from_request(request)
    uid = user.get("id") if user else None
    if not isinstance(uid, int):
        raise web.HTTPUnauthorized(text="initData invalid or expired")
    return uid


def _lang(request: web.Request) -> str:
    user = _user_from_request(request) or {}
    return user.get("language_code") or "en"


async def index(request: web.Request) -> web.StreamResponse:
    """The app shell. initData is not checked here — the page itself is public;
    every piece of DATA behind it is not."""
    return web.FileResponse(_STATIC / "app.html")


async def api_strings(request: web.Request) -> web.Response:
    lang = _lang(request)
    return web.json_response({"lang": lang, "strings": {k: t(k, lang) for k in _UI_KEYS}})


async def api_history(request: web.Request) -> web.Response:
    uid = _require_user(request)
    try:
        limit = min(int(request.query.get("limit", PAGE_SIZE)), MAX_PAGE_SIZE)
        offset = max(int(request.query.get("offset", 0)), 0)
    except ValueError:
        raise web.HTTPBadRequest(text="limit and offset must be numbers") from None
    entries = await asyncio.to_thread(abuse.user_searches, uid, limit=limit, offset=offset)
    total = await asyncio.to_thread(abuse.count_user_searches, uid)
    return web.json_response(
        {
            "total": total,
            "offset": offset,
            "entries": [
                {
                    "id": e["search_id"],
                    "at": e["searched_at"],
                    "file_id": e["file_unique_id"],
                    "has_image": bool(e.get("saved_filename")),
                    "results": e["results"],
                }
                for e in entries
            ],
        }
    )


async def api_thumb(request: web.Request) -> web.StreamResponse:
    """A history entry's picture, rendered on first view.

    Scoped by ownership: the file id in the path is only honoured if it belongs
    to one of the caller's own searches.
    """
    uid = _require_user(request)
    file_id = request.match_info["file_id"]
    owned = await asyncio.to_thread(abuse.user_owns_search_file, uid, file_id)
    if not owned:
        raise web.HTTPForbidden(text="not your search")
    path = await asyncio.to_thread(thumbs.get_or_create, file_id, owned)
    if path is None:
        # The upload was swept by retention, or never renderable. The page shows
        # a placeholder — not an error worth logging loudly.
        raise web.HTTPNotFound(text="no image")
    resp = web.FileResponse(path)
    # Content-addressed by file_unique_id, so it can be cached hard.
    resp.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    return resp


async def api_delete(request: web.Request) -> web.Response:
    uid = _require_user(request)
    try:
        body = await request.json()
        search_id = int(body["id"])
    except ValueError, KeyError, TypeError:
        raise web.HTTPBadRequest(text="id required") from None
    removed = await asyncio.to_thread(abuse.delete_user_search, uid, search_id)
    if not removed:
        raise web.HTTPNotFound(text="not found")
    return web.json_response({"ok": True})


def add_routes(app: web.Application) -> None:
    """Register the history app on an existing aiohttp application."""
    app.router.add_get("/app", index)
    app.router.add_get("/app/api/history", api_history)
    app.router.add_get("/app/api/strings", api_strings)
    app.router.add_get("/app/api/thumb/{file_id}", api_thumb)
    app.router.add_post("/app/api/delete", api_delete)
