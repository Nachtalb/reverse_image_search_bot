"""The search-history Mini App API: auth, ownership scoping, paging.

Handlers are called directly against a mocked request, matching how the report
server is tested — no extra test dependency for an aiohttp test client.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import time
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlencode

import pytest
from aiohttp import web
from PIL import Image

TOKEN = "123:abc"


def signed(user_id: int, *, auth_date: int | None = None, token: str = TOKEN) -> str:
    params = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAA",
        "user": json.dumps({"id": user_id, "username": f"u{user_id}", "language_code": "en"}),
    }
    check = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(params)


def req(init_data: str | None = None, *, query=None, match=None, json_body=None, in_query=False):
    r = MagicMock(spec=web.Request)
    q = dict(query or {})
    headers = {}
    if init_data is not None:
        if in_query:
            q["initData"] = init_data
        else:
            headers["X-Init-Data"] = init_data
    r.headers = headers
    r.query = q
    r.match_info = match or {}
    if json_body is not None:
        r.json = AsyncMock(return_value=json_body)
    else:
        r.json = AsyncMock(side_effect=ValueError("no body"))
    return r


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A fresh abuse DB + upload dir with the webapp modules pointed at them."""
    import reverse_image_search_bot.settings as settings

    updir = tmp_path / "uploads"
    updir.mkdir()
    monkeypatch.setattr(settings, "ABUSE_DB_PATH", tmp_path / "abuse.db")
    monkeypatch.setattr(settings, "TELEGRAM_API_TOKEN", TOKEN)

    import reverse_image_search_bot.config.abuse as ab

    ab._local.__dict__.clear()
    ab._all_connections.clear()
    importlib.reload(ab)
    monkeypatch.setattr(ab, "ABUSE_DB_PATH", tmp_path / "abuse.db")
    ab._local.__dict__.clear()
    ab._all_connections.clear()

    from reverse_image_search_bot.webapp import server as srv
    from reverse_image_search_bot.webapp import thumbs

    monkeypatch.setattr(thumbs, "upload_dir", lambda: updir)
    monkeypatch.setattr(srv, "abuse", ab)
    monkeypatch.setattr(srv.settings, "TELEGRAM_API_TOKEN", TOKEN)
    return type("World", (), {"abuse": ab, "srv": srv, "updir": updir})


def seed(world, user_id: int, file_id: str, *, with_image: bool = True, with_row: bool = True, results=None):
    world.abuse.record_user(user_id)
    if with_image:
        Image.new("RGB", (600, 400), (10, 120, 200)).save(world.updir / f"{file_id}.jpg")
    if with_row:
        world.abuse.record_file(file_id, saved_filename=f"{file_id}.jpg", user_id=user_id, file_type="photo")
    sid = world.abuse.record_search(user_id, chat_id=user_id, file_unique_id=file_id)
    if results:
        world.abuse.set_search_results(sid, results)
    return sid


def body(response: web.Response) -> dict:
    assert response.text is not None
    return json.loads(response.text)


class TestAuth:
    async def test_history_requires_init_data(self, world):
        with pytest.raises(web.HTTPUnauthorized):
            await world.srv.api_history(req())

    async def test_history_rejects_a_forged_signature(self, world):
        with pytest.raises(web.HTTPUnauthorized):
            await world.srv.api_history(req(signed(1, token="999:wrong")))

    async def test_history_rejects_stale_init_data(self, world):
        with pytest.raises(web.HTTPUnauthorized):
            await world.srv.api_history(req(signed(1, auth_date=int(time.time()) - 99999)))

    async def test_delete_requires_init_data(self, world):
        with pytest.raises(web.HTTPUnauthorized):
            await world.srv.api_delete(req(json_body={"id": 1}))

    async def test_thumb_requires_init_data(self, world):
        with pytest.raises(web.HTTPUnauthorized):
            await world.srv.api_thumb(req(match={"file_id": "F1"}))


class TestOwnership:
    async def test_only_your_own_entries_are_listed(self, world):
        seed(world, 1, "MINE")
        seed(world, 2, "THEIRS")
        data = body(await world.srv.api_history(req(signed(1))))
        assert data["total"] == 1
        assert [e["file_id"] for e in data["entries"]] == ["MINE"]

    async def test_a_user_id_cannot_be_forced_by_query_param(self, world):
        """The id comes from the signature; a parameter must not override it."""
        seed(world, 2, "THEIRS")
        data = body(await world.srv.api_history(req(signed(1), query={"user_id": "2"})))
        assert data["total"] == 0

    async def test_cannot_fetch_another_users_thumbnail(self, world):
        seed(world, 2, "THEIRS")
        with pytest.raises(web.HTTPForbidden):
            await world.srv.api_thumb(req(signed(1), match={"file_id": "THEIRS"}))

    async def test_cannot_delete_another_users_entry(self, world):
        sid = seed(world, 2, "THEIRS")
        with pytest.raises(web.HTTPNotFound):
            await world.srv.api_delete(req(signed(1), json_body={"id": sid}))
        assert world.abuse.count_user_searches(2) == 1


class TestHistory:
    async def test_returns_entries_with_results(self, world):
        seed(world, 1, "F1", results=[{"engine": "SauceNAO", "title": "Found", "url": "https://e.com"}])
        entry = body(await world.srv.api_history(req(signed(1))))["entries"][0]
        assert entry["has_image"] is True
        assert entry["results"][0]["engine"] == "SauceNAO"

    async def test_entry_without_a_file_row_is_flagged_imageless(self, world):
        seed(world, 1, "SWEPT", with_image=False, with_row=False)
        entry = body(await world.srv.api_history(req(signed(1))))["entries"][0]
        assert entry["has_image"] is False

    async def test_paging(self, world):
        for i in range(5):
            seed(world, 1, f"F{i}", with_image=False, with_row=False)
        first = body(await world.srv.api_history(req(signed(1), query={"limit": "2"})))
        second = body(await world.srv.api_history(req(signed(1), query={"limit": "2", "offset": "2"})))
        assert first["total"] == 5
        assert len(first["entries"]) == len(second["entries"]) == 2
        assert {e["id"] for e in first["entries"]}.isdisjoint({e["id"] for e in second["entries"]})

    async def test_page_size_is_capped(self, world):
        """A caller must not be able to pull the whole table in one request."""
        for i in range(3):
            seed(world, 1, f"F{i}", with_image=False, with_row=False)
        data = body(await world.srv.api_history(req(signed(1), query={"limit": "100000"})))
        assert len(data["entries"]) <= world.srv.MAX_PAGE_SIZE

    async def test_negative_offset_is_clamped(self, world):
        seed(world, 1, "F1", with_image=False, with_row=False)
        data = body(await world.srv.api_history(req(signed(1), query={"offset": "-5"})))
        assert data["offset"] == 0

    async def test_bad_paging_params_are_rejected(self, world):
        with pytest.raises(web.HTTPBadRequest):
            await world.srv.api_history(req(signed(1), query={"limit": "abc"}))

    async def test_empty_history(self, world):
        world.abuse.record_user(1)
        data = body(await world.srv.api_history(req(signed(1))))
        assert data["total"] == 0 and data["entries"] == []


class TestThumbnails:
    async def test_serves_a_generated_webp(self, world):
        seed(world, 1, "F1")
        resp = await world.srv.api_thumb(req(signed(1), match={"file_id": "F1"}))
        assert resp.headers["Cache-Control"].startswith("private")
        assert "immutable" in resp.headers["Cache-Control"]
        assert resp._path.read_bytes()[:4] == b"RIFF"  # WebP container

    async def test_swept_upload_is_a_404_not_a_crash(self, world):
        """The row survives retention; the bytes do not."""
        seed(world, 1, "SWEPT", with_image=False)
        with pytest.raises(web.HTTPNotFound):
            await world.srv.api_thumb(req(signed(1), match={"file_id": "SWEPT"}))

    async def test_unknown_file_is_forbidden(self, world):
        world.abuse.record_user(1)
        with pytest.raises(web.HTTPForbidden):
            await world.srv.api_thumb(req(signed(1), match={"file_id": "NOPE"}))

    async def test_init_data_may_come_from_the_query_string(self, world):
        """<img src> cannot set headers, so the thumbnail route accepts a param."""
        seed(world, 1, "F1")
        resp = await world.srv.api_thumb(req(signed(1), match={"file_id": "F1"}, in_query=True))
        assert resp.status == 200


class TestDelete:
    async def test_removes_the_entry(self, world):
        sid = seed(world, 1, "F1", with_image=False, with_row=False)
        assert body(await world.srv.api_delete(req(signed(1), json_body={"id": sid})))["ok"] is True
        assert world.abuse.count_user_searches(1) == 0

    async def test_missing_id_is_a_400(self, world):
        with pytest.raises(web.HTTPBadRequest):
            await world.srv.api_delete(req(signed(1), json_body={}))

    async def test_unknown_id_is_a_404(self, world):
        world.abuse.record_user(1)
        with pytest.raises(web.HTTPNotFound):
            await world.srv.api_delete(req(signed(1), json_body={"id": 999}))


class TestStrings:
    async def test_returns_the_ui_catalogue(self, world):
        data = body(await world.srv.api_strings(req(signed(1))))
        assert data["strings"]["app.empty"]
        assert set(data["strings"]) == set(world.srv._UI_KEYS)

    async def test_does_not_leak_the_whole_catalogue(self, world):
        data = body(await world.srv.api_strings(req(signed(1))))
        assert not any(k.startswith(("search.", "settings.", "privacy.")) for k in data["strings"])
