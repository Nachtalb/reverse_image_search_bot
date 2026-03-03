"""Shared fixtures and environment setup for tests.

Settings module calls required_env() at import time, so we must set env vars
BEFORE any reverse_image_search_bot imports happen.
"""

import os

# Set required env vars before importing the package
os.environ.setdefault("TELEGRAM_API_TOKEN", "test:fake-token")
os.environ.setdefault("UPLOADER_PATH", "/tmp/ris_test_uploads")
os.environ.setdefault("UPLOADER_URL", "https://ris-test-uploads.naa.gg")
os.environ.setdefault("SAUCENAO_API", "test-saucenao-key")
os.environ.setdefault("TRACE_API", "test-trace-key")
os.environ.setdefault("CONFIG_DB_PATH", "/tmp/ris_test_config.db")

import pytest


@pytest.fixture(autouse=True)
def _clean_upload_dir():
    """Ensure upload dir exists for tests that touch it."""
    os.makedirs("/tmp/ris_test_uploads", exist_ok=True)
