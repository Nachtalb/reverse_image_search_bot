"""Tests for the Google engine (Vision API WEB_DETECTION) — all HTTP mocked."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from yarl import URL

from reverse_image_search_bot import settings
from reverse_image_search_bot.engines.errors import RateLimitError, SearchError
from reverse_image_search_bot.engines.google import GoogleEngine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_VISION_API", "test-key")
    monkeypatch.setattr(settings, "GOOGLE_VISION_QUOTA_PATH", tmp_path / "quota.json")
    monkeypatch.setattr(settings, "GOOGLE_VISION_MONTHLY_LIMIT", 1000)
    eng = GoogleEngine()
    GoogleEngine._best_match_cache.clear()
    return eng


def _web(*, full=True, partial=False, pages=True, entities=True, labels=True):
    web: dict = {}
    if labels:
        web["bestGuessLabels"] = [{"label": "line art"}]
    if entities:
        web["webEntities"] = [
            {"description": "Line art", "score": 0.9},
            {"description": "Sketch", "score": 0.6},
            {"description": "Noise", "score": 0.05},
            {"score": 0.99},  # no description — must be skipped
        ]
    if full:
        web["fullMatchingImages"] = [{"url": "https://example.com/full.jpg"}]
    if partial:
        web["partialMatchingImages"] = [{"url": "https://example.com/partial.jpg"}]
    if pages:
        web["pagesWithMatchingImages"] = [
            {"url": "https://example.com/page1", "pageTitle": "Some <b>page</b>"},
            {"url": "https://example.com/page2", "pageTitle": "Another page"},
        ]
    return web


def _resp(status_code=200, payload=None, *, web=None):
    if payload is None:
        payload = {"responses": [{"webDetection": web if web is not None else _web()}]}
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def _post(engine, resp=None, side_effect=None):
    return patch.object(
        engine._http_client,
        "post",
        new_callable=AsyncMock,
        return_value=resp,
        side_effect=side_effect,
    )


class TestBestMatch:
    async def test_full_match(self, engine):
        with _post(engine, _resp()):
            result, meta = await engine.best_match("https://example.com/img.jpg")

        assert result["Best guess"] == "Line Art"
        assert result["Title"] == "Some page"  # highlight markup stripped
        assert result["Match"] == "Full"
        assert result["Found on"] == "2 page(s)"
        assert result["Tags"] == ["Line art", "Sketch"]  # low score / no description dropped
        assert meta["provider"] == "Google"
        assert meta["provider_url"] == URL("https://google.com/")
        assert meta["thumbnail"] == URL("https://example.com/full.jpg")
        assert meta["identifier"] == "https://example.com/page1"
        assert [b.url for b in meta["buttons"]] == [
            "https://example.com/page1",
            "https://example.com/page2",
        ]

    async def test_partial_only(self, engine):
        web = _web(full=False, partial=True, pages=False)
        with _post(engine, _resp(web=web)):
            result, meta = await engine.best_match("https://example.com/p.jpg")

        assert result["Match"] == "Partial"
        assert "Found on" not in result
        assert meta["thumbnail"] == URL("https://example.com/partial.jpg")
        assert "buttons" not in meta
        assert "identifier" not in meta

    async def test_pages_only(self, engine):
        web = _web(full=False, partial=False, pages=True)
        with _post(engine, _resp(web=web)):
            result, meta = await engine.best_match("https://example.com/po.jpg")

        assert result["Match"] == "Pages only"
        assert "thumbnail" not in meta

    async def test_no_results(self, engine):
        with _post(engine, _resp(web={})):
            result, meta = await engine.best_match("https://example.com/none.jpg")

        assert (result, meta) == ({}, {})

    async def test_missing_web_detection_key(self, engine):
        with _post(engine, _resp(payload={"responses": [{}]})):
            result, meta = await engine.best_match("https://example.com/nowd.jpg")

        assert (result, meta) == ({}, {})

    async def test_no_api_key_stays_dormant(self, engine, monkeypatch):
        monkeypatch.setattr(settings, "GOOGLE_VISION_API", None)
        with _post(engine, _resp()) as mocked:
            result, meta = await engine.best_match("https://example.com/nokey.jpg")

        assert (result, meta) == ({}, {})
        mocked.assert_not_called()

    async def test_returns_only_codec_safe_types(self, engine):
        """The result cache JSON-encodes the payload — no exotic types allowed."""
        with _post(engine, _resp()):
            result, meta = await engine.best_match("https://example.com/types.jpg")

        allowed = (str, int, float, bool, list, dict, URL, set)
        for value in result.values():
            assert isinstance(value, allowed)
        for key, value in meta.items():
            if key == "buttons":
                continue
            assert isinstance(value, allowed)


class TestErrorHandling:
    async def test_429_is_rate_limit(self, engine):
        with _post(engine, _resp(429, {})), pytest.raises(RateLimitError) as exc:
            await engine.best_match("https://example.com/429.jpg")
        assert exc.value.period == "Monthly"

    async def test_4xx_is_reported_search_error(self, engine):
        with _post(engine, _resp(403, {})), pytest.raises(SearchError) as exc:
            await engine.best_match("https://example.com/403.jpg")
        assert exc.value.report is True

    async def test_5xx_is_unreported_search_error(self, engine):
        with _post(engine, _resp(503, {})), pytest.raises(SearchError) as exc:
            await engine.best_match("https://example.com/503.jpg")
        assert exc.value.report is False

    async def test_per_request_error_is_unreported(self, engine):
        payload = {"responses": [{"error": {"message": "image download failed"}}]}
        with _post(engine, _resp(payload=payload)), pytest.raises(SearchError) as exc:
            await engine.best_match("https://example.com/imgerr.jpg")
        assert exc.value.report is False
        assert "image download failed" in str(exc.value)

    async def test_bad_body_is_unreported(self, engine):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("not json")
        with _post(engine, resp), pytest.raises(SearchError) as exc:
            await engine.best_match("https://example.com/badbody.jpg")
        assert exc.value.report is False

    async def test_transient_network_error_not_reported(self, engine):
        with (
            _post(engine, side_effect=httpx.ConnectTimeout("timed out")),
            pytest.raises(SearchError) as exc,
        ):
            await engine.best_match("https://example.com/timeout.jpg")
        assert exc.value.report is False


class TestQuota:
    def test_counter_increments_and_persists(self, engine):
        assert engine._take_quota()
        assert engine._take_quota()
        data = json.loads(settings.GOOGLE_VISION_QUOTA_PATH.read_text())
        assert data["count"] == 2

    def test_limit_enforced(self, engine, monkeypatch):
        monkeypatch.setattr(settings, "GOOGLE_VISION_MONTHLY_LIMIT", 2)
        assert engine._take_quota()
        assert engine._take_quota()
        assert not engine._take_quota()

    def test_month_rollover_resets(self, engine):
        settings.GOOGLE_VISION_QUOTA_PATH.write_text(json.dumps({"month": "1999-01", "count": 999999}))
        assert engine._take_quota()
        assert json.loads(settings.GOOGLE_VISION_QUOTA_PATH.read_text())["count"] == 1

    def test_corrupt_file_recovers(self, engine):
        settings.GOOGLE_VISION_QUOTA_PATH.write_text("not json at all")
        assert engine._take_quota()

    def test_non_dict_file_recovers(self, engine):
        settings.GOOGLE_VISION_QUOTA_PATH.write_text("[1, 2, 3]")
        assert engine._take_quota()

    def test_non_numeric_count_recovers(self, engine):
        now = datetime.now(UTC).strftime("%Y-%m")
        settings.GOOGLE_VISION_QUOTA_PATH.write_text(json.dumps({"month": now, "count": "many"}))
        assert engine._take_quota()

    def test_unwritable_path_blocks_instead_of_uncapping(self, engine, monkeypatch, tmp_path):
        # A file where the parent directory should be → mkdir raises OSError.
        blocker = tmp_path / "blocker"
        blocker.write_text("i am a file")
        monkeypatch.setattr(settings, "GOOGLE_VISION_QUOTA_PATH", blocker / "quota.json")
        assert not engine._take_quota()

    async def test_exhausted_quota_raises_rate_limit(self, engine, monkeypatch):
        monkeypatch.setattr(settings, "GOOGLE_VISION_MONTHLY_LIMIT", 0)
        with _post(engine, _resp()) as mocked, pytest.raises(RateLimitError) as exc:
            await engine.best_match("https://example.com/quota.jpg")
        assert exc.value.period == "Monthly"
        mocked.assert_not_called()

    async def test_successful_search_consumes_one_unit(self, engine):
        with _post(engine, _resp()):
            await engine.best_match("https://example.com/consume.jpg")
        assert json.loads(settings.GOOGLE_VISION_QUOTA_PATH.read_text())["count"] == 1


class TestEngineWiring:
    def test_lens_button_always_available(self, engine):
        button = engine("https://example.com/img.jpg")
        assert button.url is not None
        assert button.url.startswith("https://lens.google.com/uploadbyurl?url=")
        assert button.text == "Google"

    def test_lens_button_without_api_key(self, engine, monkeypatch):
        monkeypatch.setattr(settings, "GOOGLE_VISION_API", None)
        assert engine("https://example.com/img.jpg").url

    def test_best_match_implemented_follows_key(self, engine, monkeypatch):
        assert GoogleEngine.best_match_implemented
        monkeypatch.setattr(settings, "GOOGLE_VISION_API", None)
        assert not GoogleEngine.best_match_implemented

    def test_registered_in_engine_list(self):
        from reverse_image_search_bot.engines import engines

        google = [e for e in engines if e.name == "Google"]
        assert len(google) == 1
        assert isinstance(google[0], GoogleEngine)
