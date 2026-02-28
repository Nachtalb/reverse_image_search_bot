import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

logging.basicConfig(
    format=os.getenv(
        "LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ),
    level=logging.INFO,
)


def get_env_list(name: str) -> List[int]:
    raw = os.getenv(name, "")
    return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


TELEGRAM_API_TOKEN = required_env("TELEGRAM_API_TOKEN")

_uploader_type = os.getenv("UPLOADER_TYPE", "local")
_uploader_config: Dict[str, Any]
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

UPLOADER: Dict[str, Any] = {
    "uploader": _uploader_type,
    "url": required_env("UPLOADER_URL"),
    "configuration": _uploader_config,
}


ADMIN_IDS = get_env_list("ADMIN_IDS")

SAUCENAO_API = required_env("SAUCENAO_API")
TRACE_API = required_env("TRACE_API")
ANILIST_TOKEN = os.getenv("ANILIST_TOKEN")

MODE_ACTIVE = os.getenv("MODE_ACTIVE", "polling")

MODE: Dict[str, Any] = {
    "active": MODE_ACTIVE,
}

if MODE_ACTIVE == "webhook":
    MODE["configuration"] = {
        "listen": required_env("MODE_LISTEN"),
        "port": int(required_env("MODE_PORT")),
        "url_path": required_env("MODE_URL_PATH"),
        "webhook_url": required_env("MODE_WEBHOOK_URL"),
    }

WORKERS = int(os.getenv("WORKERS", 4))
CON_POOL_SIZE = int(os.getenv("CON_POOL_SIZE", WORKERS + 4))

CONFIG_DIR = (
    Path(os.getenv("CONFIG_DIR", "~/.config/reverse_image_search_bot"))
    .expanduser()
    .absolute()
)


# Prometheus metrics
PROMETHEUS_ENABLED = os.getenv("PROMETHEUS_ENABLED", "true").lower() in ("true", "1", "yes")
PROMETHEUS_PORT = int(os.getenv("PROMETHEUS_PORT", "9100"))

log = logging.getLogger("config")
log.info(f"UPLOADER: {json.dumps(UPLOADER, indent=2)}")
log.info(f"MODE: {json.dumps(MODE, indent=2)}")
