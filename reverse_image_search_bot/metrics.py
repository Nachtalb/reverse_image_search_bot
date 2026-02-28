"""Prometheus metrics for the Reverse Image Search Bot.

Metrics are exposed on a separate HTTP port (default 9100) and scraped by Prometheus.
Disable with PROMETHEUS_ENABLED=false.
"""

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
    ["type", "mode"],  # type: image/sticker/gif/video_frame, mode: inline/direct
)

searches_by_user_total = Counter(
    "ris_searches_by_user_total",
    "Total searches per user",
    ["user_id"],
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
    """Periodically update thread count and memory usage."""
    while True:
        active_threads.set(threading.active_count())
        try:
            # Read RSS from /proc/self/statm (Linux)
            with open("/proc/self/statm") as f:
                pages = int(f.read().split()[1])  # resident pages
                memory_bytes.set(pages * os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError):
            pass
        time.sleep(15)


def start_metrics_server():
    """Start the Prometheus metrics HTTP server if enabled."""
    if not settings.PROMETHEUS_ENABLED:
        logger.info("Prometheus metrics disabled")
        return

    port = settings.PROMETHEUS_PORT
    start_http_server(port)
    bot_start_time.set(time.time())

    # Start background thread for process metrics collection
    collector = threading.Thread(target=_collect_process_metrics, daemon=True)
    collector.start()

    logger.info(f"Prometheus metrics server started on port {port}")
