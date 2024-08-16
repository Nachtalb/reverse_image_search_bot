import os
import sys

from aiopath import AsyncPath

HOME = AsyncPath(os.path.expanduser("~"))
CACHE_DIR = HOME / ".cache/ris"
DOWNLOAD_DIR = CACHE_DIR / "downloads"
SEARCH_DIR = CACHE_DIR / "searches"
SOURCE_DIR = CACHE_DIR / "sources"

REPO_URL = "https://github.com/Nachtalb/reverse_image_search_bot"
USER_AGENT = f"ReverseImageSearch/4.0.0a0 ({sys.platform}; +{REPO_URL})"

SAUCENAO_API_KEY = os.environ.get("SAUCENAO_API_KEY")
SAUCENAO_MIN_SIMILARITY = float(os.environ.get("SAUCENAO_MIN_SIMILARITY", 80))
