"""Tests for reverse_image_search_bot.engines.trace — mocked HTTP."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from reverse_image_search_bot.engines.errors import RateLimitError
from reverse_image_search_bot.engines.trace import TraceEngine


@pytest.fixture
def engine():
    e = TraceEngine()
    e._best_match_cache.clear()
    e._use_api_key = False
    e.limit_reached = None
    return e


def _trace_result(anilist_id=12345, similarity=0.95, episode=5):
    return {
        "result": [
            {
                "anilist": anilist_id,
                "episode": episode,
                "similarity": similarity,
                "filename": "test.mp4",
                "from": 120.0,
                "to": 125.0,
                "video": "https://trace.moe/video/test.mp4",
            }
        ]
    }


@pytest.mark.asyncio
class TestTraceFetchData:
    async def test_fetch_without_api_key(self, engine):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _trace_result()

        with patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            data = await engine._fetch_data("https://example.com/img.jpg")
        assert isinstance(data, dict)
        assert "result" in data

    async def test_fetch_402_switches_to_api_key(self, engine):
        mock_402 = MagicMock()
        mock_402.status_code = 402

        mock_ok = MagicMock()
        mock_ok.status_code = 200
        mock_ok.json.return_value = _trace_result()

        with patch.object(engine._http_client, "get", new_callable=AsyncMock, side_effect=[mock_402, mock_ok]):
            data = await engine._fetch_data("https://example.com/img.jpg")
        assert engine.use_api_key is True
        assert isinstance(data, dict)

    async def test_fetch_with_api_key(self, engine):
        engine._use_api_key = True
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _trace_result()

        with patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await engine._fetch_data("https://example.com/img.jpg")
        # Should have passed x-trace-key header
        call_kwargs = mock_get.call_args
        assert "x-trace-key" in call_kwargs.kwargs.get("headers", {})

    async def test_fetch_non_200_returns_status_code(self, engine):
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch.object(engine._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            data = await engine._fetch_data("https://example.com/img.jpg")
        assert data == 500


@pytest.mark.asyncio
class TestTraceBestMatch:
    async def test_successful_with_anilist(self, engine):
        anilist_result = (
            {"Title": "Attack on Titan", "Title [romaji]": "Shingeki no Kyojin", "Episode": "5/25"},
            {
                "provided_via": "Anilist",
                "buttons": [],
            },
        )

        with (
            patch.object(engine, "_fetch_data", new_callable=AsyncMock, return_value=_trace_result(anilist_id=16498)),
            patch(
                "reverse_image_search_bot.engines.trace.anilist.provide",
                new_callable=AsyncMock,
                return_value=anilist_result,
            ),
        ):
            result, meta = await engine.best_match("https://example.com/trace1.jpg")

        assert result["Title"] == "Attack on Titan"
        assert meta["provider"] == "Trace"
        assert meta["similarity"] == 95.0
        assert "Est. Time" in result

    async def test_402_raises_rate_limit(self, engine):
        with (
            patch.object(engine, "_fetch_data", new_callable=AsyncMock, return_value=402),
            pytest.raises(RateLimitError, match="402"),
        ):
            await engine.best_match("https://example.com/trace2.jpg")

    async def test_non_200_returns_empty(self, engine):
        with patch.object(engine, "_fetch_data", new_callable=AsyncMock, return_value=500):
            result, _meta = await engine.best_match("https://example.com/trace3.jpg")
        assert result == {}

    async def test_empty_data_returns_empty(self, engine):
        with patch.object(engine, "_fetch_data", new_callable=AsyncMock, return_value={}):
            result, _meta = await engine.best_match("https://example.com/trace4.jpg")
        assert result == {}

    async def test_below_similarity_returns_empty(self, engine):
        low_sim_data = _trace_result(similarity=0.50)

        with patch.object(engine, "_fetch_data", new_callable=AsyncMock, return_value=low_sim_data):
            result, _meta = await engine.best_match("https://example.com/trace5.jpg")
        assert result == {}

    async def test_empty_results_list(self, engine):
        with patch.object(engine, "_fetch_data", new_callable=AsyncMock, return_value={"result": []}):
            result, _meta = await engine.best_match("https://example.com/trace6.jpg")
        assert result == {}

    async def test_anilist_returns_empty_falls_back(self, engine):
        """When anilist.provide returns empty, use raw data from trace."""
        data = _trace_result(anilist_id=99999)

        with (
            patch.object(engine, "_fetch_data", new_callable=AsyncMock, return_value=data),
            patch(
                "reverse_image_search_bot.engines.trace.anilist.provide",
                new_callable=AsyncMock,
                return_value=({}, {}),
            ),
        ):
            result, meta = await engine.best_match("https://example.com/trace7.jpg")

        assert result.get("Episode") == 5
        assert result.get("Filename") == "test.mp4"
        assert meta["provider"] == "Trace"

    async def test_anilist_dict_format(self, engine):
        """When anilist field is a dict (older API format)."""
        data = {
            "result": [
                {
                    "anilist": {"id": 100, "idMal": 200, "titles": {"english": "Dict Anime", "romaji": "Dict"}},
                    "episode": 3,
                    "similarity": 0.95,
                    "filename": "dict.mp4",
                    "from": 60.0,
                    "to": 65.0,
                    "video": "https://trace.moe/video/dict.mp4",
                }
            ]
        }

        with (
            patch.object(engine, "_fetch_data", new_callable=AsyncMock, return_value=data),
            patch(
                "reverse_image_search_bot.engines.trace.anilist.provide",
                new_callable=AsyncMock,
                return_value=({}, {}),
            ),
        ):
            result, meta = await engine.best_match("https://example.com/trace8.jpg")

        assert result["Title"] == "Dict Anime"
        assert result["Title [romaji]"] == "Dict"
        # Should have both anilist and MAL buttons
        assert any("anilist.co" in b.url for b in meta["buttons"])
        assert any("myanimelist.net" in b.url for b in meta["buttons"])


class TestUseApiKeyProperty:
    def test_getter(self):
        engine = TraceEngine()
        engine._use_api_key = False
        assert engine.use_api_key is False
        engine._use_api_key = True
        assert engine.use_api_key is True

    def test_setter_without_application(self):
        engine = TraceEngine()
        with patch("reverse_image_search_bot.bot.application", None):
            engine.use_api_key = True
            assert engine._use_api_key is True

    def test_setter_with_application_schedules_job(self):
        engine = TraceEngine()
        mock_app = MagicMock()
        mock_app.job_queue.get_jobs_by_name.return_value = []

        with patch("reverse_image_search_bot.bot.application", mock_app):
            engine.use_api_key = True

        mock_app.job_queue.run_monthly.assert_called_once()
        assert mock_app.job_queue.run_monthly.call_args.kwargs["name"] == "trace_api"

    def test_setter_with_existing_job_skips(self):
        engine = TraceEngine()
        mock_app = MagicMock()
        mock_app.job_queue.get_jobs_by_name.return_value = [MagicMock()]

        with patch("reverse_image_search_bot.bot.application", mock_app):
            engine.use_api_key = True

        mock_app.job_queue.run_monthly.assert_not_called()


@pytest.mark.asyncio
class TestStopUsingApiKey:
    async def test_resets_flag(self):
        engine = TraceEngine()
        engine._use_api_key = True
        await engine._stop_using_api_key(MagicMock())
        assert engine._use_api_key is False
