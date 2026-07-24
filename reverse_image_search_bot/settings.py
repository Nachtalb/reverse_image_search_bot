import json
import logging
import os
from pathlib import Path
from typing import Any

logging.basicConfig(
    format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
    level=logging.INFO,
)


def get_env_list(name: str) -> list[int]:
    raw = os.getenv(name, "")
    return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


TELEGRAM_API_TOKEN = required_env("TELEGRAM_API_TOKEN")

_uploader_type = os.getenv("UPLOADER_TYPE", "local")
_uploader_config: dict[str, Any]
if _uploader_type == "ssh":
    _uploader_config = {
        "host": required_env("UPLOADER_HOST"),
        "user": required_env("UPLOADER_USER"),
        "password": required_env("UPLOADER_PASSWORD"),
        "upload_dir": required_env("UPLOADER_UPLOAD_DIR"),
        "key_filename": os.getenv("UPLOADER_KEY_FILENAME"),
    }
else:
    _uploader_config = {"path": required_env("UPLOADER_PATH")}

UPLOADER: dict[str, Any] = {
    "uploader": _uploader_type,
    "url": required_env("UPLOADER_URL"),
    "configuration": _uploader_config,
}


ADMIN_IDS = get_env_list("ADMIN_IDS")

SAUCENAO_API = required_env("SAUCENAO_API")
TRACE_API = required_env("TRACE_API")
ANILIST_TOKEN = os.getenv("ANILIST_TOKEN")

# Google Cloud Vision API key for the Google best match (WEB_DETECTION).
# Optional — when unset the Google engine is URL-button-only.
GOOGLE_VISION_API = os.getenv("GOOGLE_VISION_API")
# Free tier: 1000 units/month. Persisted counter so it survives restarts.
GOOGLE_VISION_MONTHLY_LIMIT = int(os.getenv("GOOGLE_VISION_MONTHLY_LIMIT", "1000"))

MODE_ACTIVE = os.getenv("MODE_ACTIVE", "polling")

MODE: dict[str, Any] = {
    "active": MODE_ACTIVE,
}

if MODE_ACTIVE == "webhook":
    MODE["configuration"] = {
        "listen": required_env("MODE_LISTEN"),
        "port": int(required_env("MODE_PORT")),
        "url_path": required_env("MODE_URL_PATH"),
        "webhook_url": required_env("MODE_WEBHOOK_URL"),
    }

CONCURRENT_UPDATES = int(os.getenv("CONCURRENT_UPDATES", 16))

_DEFAULT_CONFIG_DIR = Path("~/.config/reverse_image_search_bot").expanduser().absolute()

OLD_CONFIG_DIR = Path(os.getenv("OLD_CONFIG_DIR", str(_DEFAULT_CONFIG_DIR))).expanduser().absolute()

PIXIV_CONFIG = Path(os.getenv("PIXIV_CONFIG", str(_DEFAULT_CONFIG_DIR / "pixiv.json"))).expanduser().absolute()

CONFIG_DB_PATH = Path(os.getenv("CONFIG_DB_PATH", str(_DEFAULT_CONFIG_DIR / "config.db"))).expanduser().absolute()

# Abuse-report DB (uploader/file provenance for NCMEC reports + durable ban
# list). Separate file so it can be handled/backed-up independently of settings.
ABUSE_DB_PATH = Path(os.getenv("ABUSE_DB_PATH", str(_DEFAULT_CONFIG_DIR / "abuse.db"))).expanduser().absolute()

PERSISTENCE_PATH = (
    Path(os.getenv("PERSISTENCE_PATH", str(_DEFAULT_CONFIG_DIR / "bot_data.pickle"))).expanduser().absolute()
)

# Persisted monthly usage counter for the Google Vision best match.
GOOGLE_VISION_QUOTA_PATH = (
    Path(os.getenv("GOOGLE_VISION_QUOTA_PATH", str(_DEFAULT_CONFIG_DIR / "google_vision_quota.json")))
    .expanduser()
    .absolute()
)


# Prometheus metrics
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() in ("true", "1", "yes")
METRICS_PORT = int(os.getenv("RIS_METRICS_PORT", "9100"))


# --- Abuse-report webview (NCMEC) ---------------------------------------------
# The report page is served by an aiohttp app; the admin opens it via a Telegram
# Mini App menu button. All of these are optional — when unset the /report
# command and web server stay dormant.
REPORT_SERVER_ENABLED = os.getenv("REPORT_SERVER_ENABLED", "false").lower() in ("true", "1", "yes")
REPORT_SERVER_HOST = os.getenv("REPORT_SERVER_HOST", "0.0.0.0")
REPORT_SERVER_PORT = int(os.getenv("REPORT_SERVER_PORT", "9200"))
# Public base URL the Mini App is reachable at, e.g. https://ris.naa.gg/report
REPORT_BASE_URL = os.getenv("REPORT_BASE_URL", "").rstrip("/")
# Single global page password gating the report webview. Combined with the per-report image key (P1), this is
# the second of the two secrets. When unset the page gate is effectively open to
# any authenticated admin (initData still required).
REPORT_PAGE_PASSWORD = os.getenv("REPORT_PAGE_PASSWORD", "")

# NCMEC CyberTipline credentials. Report filing is disabled if unset.
NCMEC_USERNAME = os.getenv("NCMEC_USERNAME")
NCMEC_PASSWORD = os.getenv("NCMEC_PASSWORD")
NCMEC_TESTING = os.getenv("NCMEC_TESTING", "false").lower() in ("true", "1", "yes")
# Reporter identity stamped on every NCMEC report.
NCMEC_REPORTER_FIRST_NAME = os.getenv("NCMEC_REPORTER_FIRST_NAME", "")
NCMEC_REPORTER_LAST_NAME = os.getenv("NCMEC_REPORTER_LAST_NAME", "")
NCMEC_REPORTER_EMAIL = os.getenv("NCMEC_REPORTER_EMAIL", "")
NCMEC_ESP_NAME = os.getenv("NCMEC_ESP_NAME", "")
# Short terms-of-service statement stamped on the reporter (how we handle the
# reported data). Free text; blank to omit.
NCMEC_TERMS_OF_SERVICE = os.getenv(
    "NCMEC_TERMS_OF_SERVICE",
    "Reverse Image Search Bot operates under Telegram's Third-Party Developer Terms. "
    "Data is retained solely for abuse reporting.",
)

log = logging.getLogger("config")
log.info(f"UPLOADER: {json.dumps(UPLOADER, indent=2)}")
log.info(f"MODE: {json.dumps(MODE, indent=2)}")
