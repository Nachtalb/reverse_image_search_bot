"""Report sources, ingest API keys and the authenticated ingest endpoint."""

from __future__ import annotations

import importlib
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web


@pytest.fixture
def abuse(tmp_path, monkeypatch):
    import reverse_image_search_bot.settings as settings

    db_path = tmp_path / "abuse.db"
    monkeypatch.setattr(settings, "ABUSE_DB_PATH", db_path)
    import reverse_image_search_bot.config.abuse as ab

    ab._local.__dict__.clear()
    ab._all_connections.clear()
    importlib.reload(ab)
    monkeypatch.setattr(ab, "ABUSE_DB_PATH", db_path)
    ab._local.__dict__.clear()
    ab._all_connections.clear()
    return ab


def _req(headers=None, json_body=None, method="GET", app=None):
    r = MagicMock(spec=web.Request)
    r.headers = headers or {}
    r.query = {}
    r.match_info = {}
    r.method = method
    r.app = app if app is not None else {"bot": None}
    if json_body is not None:
        r.json = AsyncMock(return_value=json_body)
    return r


def _json(resp):
    import json

    return json.loads(resp.text)


# --- sources ------------------------------------------------------------------


def test_default_source_seeded_and_used(abuse):
    names = [s["name"] for s in abuse.list_sources()]
    assert names == [abuse.DEFAULT_SOURCE]

    abuse.record_user(1)
    abuse.create_report("r1", 1, "")
    row = abuse._get_conn().execute("SELECT source_id FROM reports WHERE report_uuid='r1'").fetchone()
    assert row["source_id"] == abuse.get_source_by_name(abuse.DEFAULT_SOURCE)["id"]


def test_source_add_delete_rules(abuse):
    sid = abuse.add_source("cybertip")
    with pytest.raises(sqlite3.IntegrityError):
        abuse.add_source("cybertip")

    # The default source is permanent.
    default_id = abuse.get_source_by_name(abuse.DEFAULT_SOURCE)["id"]
    assert abuse.delete_source(default_id)

    # An unused source goes; a used one is kept.
    assert abuse.delete_source(sid) is None
    sid = abuse.add_source("cybertip")
    abuse.record_user(1)
    abuse.create_report("r1", 1, "", sid)
    assert "1 report(s)" in (abuse.delete_source(sid) or "")
    assert abuse.list_sources()[-1]["reports"] == 1


def test_migration_adds_sources_to_old_db(tmp_path, monkeypatch):
    """A reports table created before sources gets source_id + the sweep backfill."""
    import reverse_image_search_bot.settings as settings

    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE users (user_id INTEGER PRIMARY KEY, first_seen INTEGER, last_seen INTEGER)")
    conn.execute(
        "CREATE TABLE reports (report_uuid TEXT PRIMARY KEY, user_id INTEGER NOT NULL, "
        "page_secret_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'preparing', "
        "created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)"
    )
    conn.execute("INSERT INTO users VALUES (5, 0, 0)")
    conn.execute("INSERT INTO reports VALUES ('OLD', 5, '', 'filed', 0, 0)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "ABUSE_DB_PATH", db_path)
    import reverse_image_search_bot.config.abuse as ab

    ab._local.__dict__.clear()
    ab._all_connections.clear()
    importlib.reload(ab)
    monkeypatch.setattr(ab, "ABUSE_DB_PATH", db_path)
    ab._local.__dict__.clear()
    ab._all_connections.clear()

    cols = {r["name"] for r in ab._get_conn().execute("PRAGMA table_info(reports)")}
    assert "source_id" in cols
    # The pre-existing report is attributed to the default source, not left NULL.
    row = ab._get_conn().execute("SELECT source_id FROM reports WHERE report_uuid='OLD'").fetchone()
    assert row["source_id"] == (ab.get_source_by_name(ab.DEFAULT_SOURCE) or {})["id"]


def test_filed_stats_carry_source(abuse):
    sid = abuse.add_source("cloudflare")
    abuse.record_user(1)
    abuse.create_report("r1", 1, "", sid)
    abuse.mark_report_filed("r1")
    abuse.record_user(2)
    abuse.create_report("r2", 2, "")
    abuse.mark_report_filed("r2")
    sources = sorted(r["source"] for r in abuse.filed_report_stats())
    assert sources == ["cloudflare", abuse.DEFAULT_SOURCE]


# --- API keys -----------------------------------------------------------------


def test_api_key_masked_and_rotatable(abuse):
    from reverse_image_search_bot.abuse_report import crypto

    key = crypto.gen_api_key()
    kid = abuse.add_api_key("feed", crypto.hash_api_key(key), crypto.mask_api_key(key))

    listed = abuse.list_api_keys()[0]
    # The secret never leaves the DB — only the mask does.
    assert "key_hash" not in listed
    assert listed["key_preview"] == crypto.mask_api_key(key) != key
    assert listed["key_preview"].startswith("ris_") and listed["key_preview"].endswith(key[-4:])

    assert abuse.api_key_by_hash(crypto.hash_api_key(key))["name"] == "feed"
    assert abuse.list_api_keys()[0]["last_used_at"] is not None

    new = crypto.gen_api_key()
    assert abuse.rotate_api_key(kid, crypto.hash_api_key(new), crypto.mask_api_key(new))
    # The old key stops working the moment it is rotated.
    assert abuse.api_key_by_hash(crypto.hash_api_key(key)) is None
    assert abuse.api_key_by_hash(crypto.hash_api_key(new))["id"] == kid

    assert abuse.delete_api_key(kid)
    assert abuse.list_api_keys() == []


@pytest.mark.asyncio
async def test_keys_endpoint_returns_key_once(abuse, monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)

    created = _json(await server.api_keys(_req(method="POST", json_body={"action": "add", "name": "feed"})))
    assert created["new_key"].startswith("ris_")

    # A later listing only ever returns the mask.
    listed = _json(await server.api_keys(_req()))
    assert listed["new_key"] is None
    assert listed["keys"][0]["key_preview"] != created["new_key"]

    kid = listed["keys"][0]["id"]
    rotated = _json(await server.api_keys(_req(method="POST", json_body={"action": "rotate", "id": kid})))
    assert rotated["new_key"] and rotated["new_key"] != created["new_key"]


# --- ingest -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_requires_valid_key(abuse):
    from reverse_image_search_bot.abuse_report import server

    with pytest.raises(web.HTTPUnauthorized):
        await server.api_ingest(_req(json_body={"source": "x", "targets": ["1"]}))
    with pytest.raises(web.HTTPUnauthorized):
        await server.api_ingest(
            _req(headers={"Authorization": "Bearer nope"}, json_body={"source": "x", "targets": ["1"]})
        )


@pytest.mark.asyncio
async def test_ingest_creates_reports_without_returning_the_image_key(abuse, monkeypatch):
    from reverse_image_search_bot.abuse_report import crypto, server

    key = crypto.gen_api_key()
    abuse.add_api_key("feed", crypto.hash_api_key(key), crypto.mask_api_key(key))
    sid = abuse.add_source("cloudflare")
    auth = {"Authorization": f"Bearer {key}"}

    # An unknown source is refused — sources are created before they are used.
    with pytest.raises(web.HTTPBadRequest):
        await server.api_ingest(_req(headers=auth, json_body={"source": "nope", "targets": ["7"]}))

    monkeypatch.setattr(server, "resolve_targets", lambda text: ([7], ["ghost"], {}))

    class _Result:
        ok = True
        report_uuid = "uuid7"
        p1 = "secret-image-key"
        encrypted = 3

    prepared = {}

    def fake_prepare(user_id, progress, indicators, source_id):
        prepared.update(user_id=user_id, source_id=source_id)
        return _Result()

    monkeypatch.setattr(server, "prepare_report", fake_prepare)
    bot = MagicMock()
    bot.send_message = AsyncMock()
    monkeypatch.setattr("reverse_image_search_bot.settings.ADMIN_IDS", [1, 2])

    body = _json(
        await server.api_ingest(
            _req(headers=auth, json_body={"source": "cloudflare", "targets": ["7"]}, app={"bot": bot})
        )
    )

    assert prepared == {"user_id": 7, "source_id": sid}
    assert body["source"] == "cloudflare"
    assert body["unknown"] == ["ghost"]
    # P1 is DM'd to every admin, never returned over the API.
    assert "p1" not in body["results"][0]
    assert "secret-image-key" not in str(body)
    assert [c.args[0] for c in bot.send_message.call_args_list] == [1, 2]
    assert "secret-image-key" in bot.send_message.call_args_list[0].args[1]
    assert "via cloudflare" in bot.send_message.call_args_list[0].args[1]
