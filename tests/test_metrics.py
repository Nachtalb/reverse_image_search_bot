"""Tests for reverse_image_search_bot.metrics — verify metrics are importable and properly defined."""

from reverse_image_search_bot import metrics


class TestMetricsDefined:
    def test_counters_exist(self):
        assert metrics.searches_total is not None
        assert metrics.commands_total is not None
        assert metrics.provider_results_total is not None
        assert metrics.data_provider_total is not None
        assert metrics.errors_total is not None
        assert metrics.files_received_total is not None
        assert metrics.search_results_total is not None

    def test_histograms_exist(self):
        assert metrics.search_duration_seconds is not None
        assert metrics.data_provider_duration_seconds is not None
        assert metrics.file_size_bytes is not None

    def test_gauges_exist(self):
        assert metrics.bot_start_time is not None
        assert metrics.engine_status is not None
        assert metrics.data_provider_status is not None
        assert metrics.active_threads is not None
        assert metrics.memory_bytes is not None
        assert metrics.concurrent_searches is not None

    def test_counter_labels(self):
        # Verify we can create labeled instances without error
        metrics.searches_total.labels(type="photo", language="en")
        metrics.provider_results_total.labels(provider="SauceNAO", status="hit")
        metrics.data_provider_total.labels(provider="anilist", status="miss")
        metrics.commands_total.labels(command="start")

    def test_histogram_labels(self):
        metrics.search_duration_seconds.labels(provider="SauceNAO")
        metrics.data_provider_duration_seconds.labels(provider="pixiv")

    def test_gauge_labels(self):
        metrics.engine_status.labels(engine="SauceNAO")
        metrics.data_provider_status.labels(provider="anilist")
