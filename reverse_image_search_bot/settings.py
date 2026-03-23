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
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

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

PERSISTENCE_PATH = (
    Path(os.getenv("PERSISTENCE_PATH", str(_DEFAULT_CONFIG_DIR / "bot_data.pickle"))).expanduser().absolute()
)


# Subscription / payment limits — Free tier
FREE_DAILY_LIMIT = int(os.getenv("FREE_DAILY_LIMIT", "20"))
FREE_MONTHLY_LIMIT = int(os.getenv("FREE_MONTHLY_LIMIT", "200"))

# Subscription / payment limits — Premium tier
PREMIUM_DAILY_LIMIT = int(os.getenv("PREMIUM_DAILY_LIMIT", "100"))
PREMIUM_GOOGLE_DAILY_LIMIT = int(os.getenv("PREMIUM_GOOGLE_DAILY_LIMIT", "20"))

# Subscription pricing (Stars): [(label, days, price)]
SUBSCRIPTION_TIERS: list[tuple[str, int, int]] = [
    ("1 week", 7, 100),
    ("1 month", 30, 300),
    ("6 months", 180, 1500),
    ("12 months", 365, 3000),
]

# Prometheus metrics
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() in ("true", "1", "yes")
METRICS_PORT = int(os.getenv("RIS_METRICS_PORT", "9100"))

log = logging.getLogger("config")
log.info(f"UPLOADER: {json.dumps(UPLOADER, indent=2)}")
log.info(f"MODE: {json.dumps(MODE, indent=2)}")
