"""Tests for the persistent best-match result cache."""

import json
import sqlite3
import time

import pytest
from telegram import InlineKeyboardButton
from yarl import URL

from reverse_image_search_bot import settings
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

    def test_expired_row_is_a_miss(self):
        result_cache.put("SauceNAO", "https://x/1.jpg", PAYLOAD)
        far = time.time() + result_cache.ttl_seconds(PAYLOAD) + 60
        assert result_cache.get("SauceNAO", "https://x/1.jpg", now=far) is None

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

    def test_sweep_removes_only_expired(self):
        now = time.time()
        past = now - result_cache.ttl_seconds(PAYLOAD) - 60
        result_cache.put("SauceNAO", "https://old.jpg", PAYLOAD, now=past)
        result_cache.put("SauceNAO", "https://new.jpg", PAYLOAD, now=now)
        assert result_cache.sweep(now=now) == 1
        assert result_cache.get("SauceNAO", "https://new.jpg", now=now) is not None


EMPTY: tuple[dict, dict] = ({}, {})


class TestEmptyResultTtl:
    """A search that found nothing must not be trusted for as long as a hit.

    The engines index new images continuously, so an image with no match today
    may well have one next week; caching the negative for the full period would
    keep answering "nothing found" from a stale row for weeks.
    """

    def test_is_empty(self):
        assert result_cache.is_empty(EMPTY)
        assert result_cache.is_empty(({}, {}))
        assert not result_cache.is_empty(PAYLOAD)
        assert not result_cache.is_empty(({}, {"provider": "SauceNAO"}))
        assert not result_cache.is_empty(({"Title": "x"}, {}))

    def test_empty_gets_the_short_ttl(self):
        assert result_cache.ttl_seconds(EMPTY) == settings.RESULT_CACHE_EMPTY_TTL_HOURS * 3600
        assert result_cache.ttl_seconds(PAYLOAD) == settings.RESULT_CACHE_TTL_DAYS * 86400
        assert result_cache.ttl_seconds(EMPTY) < result_cache.ttl_seconds(PAYLOAD)

    def test_empty_is_still_served_inside_its_window(self):
        result_cache.put("SauceNAO", "https://x/1.jpg", EMPTY)
        assert result_cache.get("SauceNAO", "https://x/1.jpg") == EMPTY

    def test_empty_expires_while_a_hit_survives(self):
        result_cache.put("SauceNAO", "https://miss.jpg", EMPTY)
        result_cache.put("SauceNAO", "https://hit.jpg", PAYLOAD)
        later = time.time() + settings.RESULT_CACHE_EMPTY_TTL_HOURS * 3600 + 60
        assert result_cache.get("SauceNAO", "https://miss.jpg", now=later) is None
        assert result_cache.get("SauceNAO", "https://hit.jpg", now=later) is not None

    def test_a_later_hit_overwrites_the_stored_expiry(self):
        """The image got indexed: re-searching must upgrade the row's lifetime."""
        result_cache.put("SauceNAO", "https://x/1.jpg", EMPTY)
        result_cache.put("SauceNAO", "https://x/1.jpg", PAYLOAD)
        later = time.time() + settings.RESULT_CACHE_EMPTY_TTL_HOURS * 3600 + 60
        got = result_cache.get("SauceNAO", "https://x/1.jpg", now=later)
        assert got is not None
        assert got[0]["Title"] == "Some Title"

    def test_sweep_clears_expired_empties(self):
        now = time.time()
        result_cache.put("SauceNAO", "https://miss.jpg", EMPTY)
        result_cache.put("SauceNAO", "https://hit.jpg", PAYLOAD)
        later = now + settings.RESULT_CACHE_EMPTY_TTL_HOURS * 3600 + 60
        assert result_cache.sweep(now=later) == 1
        assert result_cache.get("SauceNAO", "https://hit.jpg", now=later) is not None


class TestMigration:
    def test_adds_expires_at_to_an_old_cache_table(self, tmp_path, monkeypatch):
        """A DB created before expires_at must gain it, backfilled from created_at."""
        from reverse_image_search_bot.config import db

        path = tmp_path / "old.db"
        old = sqlite3.connect(str(path))
        old.execute(
            "CREATE TABLE best_match_cache (engine TEXT NOT NULL, image_url TEXT NOT NULL, "
            "payload TEXT NOT NULL, created_at INTEGER NOT NULL, PRIMARY KEY (engine, image_url))"
        )
        stamp = int(time.time())
        old.execute(
            "INSERT INTO best_match_cache VALUES (?, ?, ?, ?)",
            ("SauceNAO", "https://x/1.jpg", result_cache.encode(PAYLOAD), stamp),
        )
        old.commit()
        old.close()

        monkeypatch.setattr(db, "CONFIG_DB_PATH", path)
        monkeypatch.setattr(db._local, "conn", None, raising=False)

        row = db.connection().execute("SELECT expires_at FROM best_match_cache").fetchone()
        assert row["expires_at"] == stamp + settings.RESULT_CACHE_TTL_DAYS * 86400
        assert result_cache.get("SauceNAO", "https://x/1.jpg") is not None
        monkeypatch.setattr(db._local, "conn", None, raising=False)


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
