"""Tests for the persistent best-match result cache."""

import json
import sqlite3
import time

import pytest
from telegram import InlineKeyboardButton
from yarl import URL

from reverse_image_search_bot.config import result_cache


@pytest.fixture(autouse=True)
def cache_db(tmp_path, monkeypatch):
    """Point the config DB at a temp file and reset thread-local connections."""
    from reverse_image_search_bot.config import db

    monkeypatch.setattr(db, "CONFIG_DB_PATH", tmp_path / "config.db")
    monkeypatch.setattr(db._local, "conn", None, raising=False)
    yield tmp_path / "config.db"
    monkeypatch.setattr(db._local, "conn", None, raising=False)


PAYLOAD = (
    {
        "Title": "Some Title",
        "Pages": 12,
        "Source": URL("https://example.com/post/1"),
        "Tags": {"beta", "alpha"},
        "Artists": ["someone", "else"],
    },
    {
        "provider": "SauceNAO",
        "provider_url": URL("https://saucenao.com"),
        "similarity": 92.4,
        "thumbnail": URL("https://example.com/t.jpg"),
        "errors": ["nope"],
        "buttons": [InlineKeyboardButton(text="Open", url="https://example.com/post/1")],
    },
)


class TestCodec:
    def test_round_trip_preserves_types(self):
        result, meta = result_cache.decode(result_cache.encode(PAYLOAD))
        assert result["Title"] == "Some Title"
        assert result["Pages"] == 12
        assert isinstance(result["Source"], URL)
        assert result["Source"] == URL("https://example.com/post/1")
        assert result["Tags"] == {"alpha", "beta"}
        assert result["Artists"] == ["someone", "else"]
        assert isinstance(meta["provider_url"], URL)
        assert meta["similarity"] == 92.4
        assert isinstance(meta["thumbnail"], URL)
        assert meta["errors"] == ["nope"]
        assert isinstance(meta["buttons"][0], InlineKeyboardButton)
        assert meta["buttons"][0].url == "https://example.com/post/1"

    def test_thumbnail_list_of_urls(self):
        payload = ({}, {"thumbnail": [URL("https://a/1.jpg"), URL("https://b/2.jpg")]})
        _, meta = result_cache.decode(result_cache.encode(payload))
        assert all(isinstance(u, URL) for u in meta["thumbnail"])
        assert [str(u) for u in meta["thumbnail"]] == ["https://a/1.jpg", "https://b/2.jpg"]

    def test_encode_is_json(self):
        assert isinstance(json.loads(result_cache.encode(PAYLOAD)), list)

    def test_empty_payload(self):
        assert result_cache.decode(result_cache.encode(({}, {}))) == ({}, {})


class TestStore:
    def test_miss_returns_none(self):
        assert result_cache.get("SauceNAO", "https://x/1.jpg") is None

    def test_put_then_get(self):
        result_cache.put("SauceNAO", "https://x/1.jpg", PAYLOAD)
        got = result_cache.get("SauceNAO", "https://x/1.jpg")
        assert got is not None
        assert got[0]["Title"] == "Some Title"
        assert isinstance(got[1]["buttons"][0], InlineKeyboardButton)

    def test_scoped_per_engine(self):
        result_cache.put("SauceNAO", "https://x/1.jpg", PAYLOAD)
        assert result_cache.get("trace.moe", "https://x/1.jpg") is None

    def test_survives_a_fresh_process(self, cache_db, monkeypatch):
        """A new connection against the same file still hits — the point of the change."""
        from reverse_image_search_bot.config import db

        result_cache.put("SauceNAO", "https://x/1.jpg", PAYLOAD)
        monkeypatch.setattr(db._local, "conn", None, raising=False)
        assert result_cache.get("SauceNAO", "https://x/1.jpg") is not None

    def test_expired_row_is_a_miss(self, monkeypatch):
        result_cache.put("SauceNAO", "https://x/1.jpg", PAYLOAD)
        monkeypatch.setattr(result_cache, "ttl_seconds", lambda: 60)
        assert result_cache.get("SauceNAO", "https://x/1.jpg", now=time.time() + 120) is None

    def test_put_overwrites(self):
        result_cache.put("SauceNAO", "https://x/1.jpg", ({"Title": "old"}, {}))
        result_cache.put("SauceNAO", "https://x/1.jpg", ({"Title": "new"}, {}))
        got = result_cache.get("SauceNAO", "https://x/1.jpg")
        assert got is not None
        assert got[0]["Title"] == "new"

    def test_undecodable_payload_is_a_miss_not_a_crash(self):
        from reverse_image_search_bot.config import db

        result_cache.put("SauceNAO", "https://x/1.jpg", PAYLOAD)
        db.connection().execute("UPDATE best_match_cache SET payload = 'not json'")
        db.connection().commit()
        assert result_cache.get("SauceNAO", "https://x/1.jpg") is None

    def test_sweep_removes_only_expired(self, monkeypatch):
        result_cache.put("SauceNAO", "https://old.jpg", PAYLOAD)
        monkeypatch.setattr(result_cache, "ttl_seconds", lambda: 60)
        result_cache.put("SauceNAO", "https://new.jpg", PAYLOAD, now=time.time() + 120)
        assert result_cache.sweep(now=time.time() + 120) == 1
        assert result_cache.get("SauceNAO", "https://new.jpg", now=time.time() + 120) is not None


class TestDecorator:
    async def test_caches_across_calls(self):
        calls = []

        class Engine:
            name = "SauceNAO"

            @result_cache.cached_best_match
            async def best_match(self, url):
                calls.append(url)
                return PAYLOAD

        engine = Engine()
        first = await engine.best_match(URL("https://x/1.jpg"))
        second = await engine.best_match(URL("https://x/1.jpg"))
        assert len(calls) == 1
        assert first[0]["Title"] == second[0]["Title"] == "Some Title"
        assert isinstance(second[0]["Source"], URL)

    async def test_store_failure_degrades_to_a_live_search(self, monkeypatch):
        calls = []

        def boom(*_args, **_kwargs):
            raise sqlite3.OperationalError("disk gone")

        monkeypatch.setattr(result_cache, "get", boom)
        monkeypatch.setattr(result_cache, "put", boom)

        class Engine:
            name = "SauceNAO"

            @result_cache.cached_best_match
            async def best_match(self, url):
                calls.append(url)
                return PAYLOAD

        assert (await Engine().best_match(URL("https://x/1.jpg")))[0]["Title"] == "Some Title"
        assert len(calls) == 1
