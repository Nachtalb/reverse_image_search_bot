"""Prometheus metrics for the Reverse Image Search Bot.

Metrics are exposed on a separate HTTP port (default 9100) and scraped by Prometheus.
Disable with METRICS_ENABLED=false.
"""

import contextlib
import logging
import os
import threading
import time

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from . import settings

logger = logging.getLogger(__name__)

# ── Usage Stats ──────────────────────────────────────────────────────────────

searches_total = Counter(
    "ris_searches_total",
    "Total reverse image searches",
    ["type", "language"],  # type: image/sticker/gif/video_frame, language: user language_code
)

searches_by_user_total = Counter(
    "ris_searches_by_user_total",
    "Total searches per user",
    ["user_id"],
)

# ── Settings / Engine Stats ──────────────────────────────────────────────────

engine_auto_disabled_total = Counter(
    "ris_engine_auto_disabled_total",
    "Times an engine was auto-disabled due to consecutive empty results",
    ["engine"],
)

engine_manual_toggle_total = Counter(
    "ris_engine_manual_toggle_total",
    "Manual engine toggle actions by users",
    ["engine", "menu", "action"],  # menu: auto_search/button, action: enabled/disabled
)

commands_total = Counter(
    "ris_commands_total",
    "Total bot command invocations",
    ["command"],  # start/help/search/settings/id/restart/ban
)

button_toggle_total = Counter(
    "ris_button_toggle_total",
    "Manual button toggle actions by users (best_match, show_link)",
    ["button", "action"],  # action: enabled/disabled
)

# ── Performance Stats ────────────────────────────────────────────────────────

search_duration_seconds = Histogram(
    "ris_search_duration_seconds",
    "Search duration per provider in seconds",
    ["provider"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

provider_results_total = Counter(
    "ris_provider_results_total",
    "Search results per provider and status",
    ["provider", "status"],  # status: hit/miss/timeout/error
)

data_provider_total = Counter(
    "ris_data_provider_total",
    "Data provider calls and outcomes",
    ["provider", "status"],  # provider: pixiv/anilist/booru/mangadex, status: hit/miss/error
)

data_provider_duration_seconds = Histogram(
    "ris_data_provider_duration_seconds",
    "Data provider call duration in seconds",
    ["provider"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

concurrent_searches = Gauge(
    "ris_concurrent_searches",
    "Number of currently running searches",
)

# ── Content Stats ────────────────────────────────────────────────────────────

files_received_total = Counter(
    "ris_files_received_total",
    "Total files received by type",
    ["file_type"],  # photo/sticker/gif/video/document
)

file_size_bytes = Histogram(
    "ris_file_size_bytes",
    "File sizes received in bytes",
    ["file_type"],
    buckets=(1024, 10240, 102400, 1048576, 10485760, 52428800),  # 1K, 10K, 100K, 1M, 10M, 50M
)

search_results_total = Counter(
    "ris_search_results_total",
    "Search outcomes",
    ["has_results"],  # true/false
)

# ── Bot Health ───────────────────────────────────────────────────────────────

bot_start_time = Gauge(
    "ris_bot_start_timestamp_seconds",
    "Unix timestamp when the bot started",
)

# ── Provider Status ───────────────────────────────────────────────────────────
# 1 = healthy, 0.5 = degraded, 0 = inactive
engine_status = Gauge(
    "ris_engine_status",
    "Search engine status (1=ok, 0.5=degraded, 0=inactive)",
    ["engine"],
)

data_provider_status = Gauge(
    "ris_data_provider_status",
    "Data provider status (1=ok, 0.5=degraded, 0=inactive)",
    ["provider"],
)

active_threads = Gauge(
    "ris_active_threads",
    "Current number of active threads",
)

memory_bytes = Gauge(
    "ris_memory_bytes",
    "Process RSS memory usage in bytes",
)

errors_total = Counter(
    "ris_errors_total",
    "Total uncaught errors",
    ["type"],  # exception class name
)


def _collect_process_metrics():
    """Periodically update thread count, memory usage, and provider status."""
    # Wait for imports to settle before first provider status check
    _first_run = True
    while True:
        active_threads.set(threading.active_count())
        try:
            with open("/proc/self/statm") as f:
                pages = int(f.read().split()[1])
                memory_bytes.set(pages * os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError):
            pass
        if _first_run:
            time.sleep(5)  # let engines/providers initialize
            _first_run = False
        with contextlib.suppress(Exception):
            update_provider_status()
        time.sleep(15)


def update_provider_status():
    """Evaluate and set status gauges for all engines and data providers."""
    from . import settings
    from .engines import engines as engine_list
    from .engines.data_providers import provides as provider_list

    for engine in engine_list:
        if not engine.best_match_implemented:
            continue  # skip link-only engines (Google, Bing, etc.)
        name = engine.name
        # Check for recent errors
        try:
            error_count = provider_results_total.labels(provider=name, status="error")._value.get()
        except Exception:
            error_count = 0

        if name == "SauceNAO" and not settings.SAUCENAO_API:
            engine_status.labels(engine=name).set(0.5)  # works but rate-limited without key
        elif error_count > 0:
            engine_status.labels(engine=name).set(0.5)
        else:
            engine_status.labels(engine=name).set(1)

    for provider in provider_list:
        name = provider.info.get("name", type(provider).__name__).lower()

        # Check provider-specific conditions
        if hasattr(provider, "authenticated") and not provider.authenticated:
            data_provider_status.labels(provider=name).set(0)  # e.g. pixiv without creds
        else:
            try:
                error_count = data_provider_total.labels(provider=name, status="error")._value.get()
            except Exception:
                error_count = 0

            if error_count > 0:
                data_provider_status.labels(provider=name).set(0.5)
            else:
                data_provider_status.labels(provider=name).set(1)


def start_metrics_server():
    """Start the Prometheus metrics HTTP server if enabled."""
    if not settings.METRICS_ENABLED:
        logger.info("Prometheus metrics disabled")
        return

    port = settings.METRICS_PORT
    start_http_server(port)
    bot_start_time.set(time.time())

    # Start background thread for process metrics collection
    collector = threading.Thread(target=_collect_process_metrics, daemon=True)
    collector.start()

    logger.info(f"Prometheus metrics server started on port {port}")
