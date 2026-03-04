"""Lightweight i18n — TOML string catalogs with fallback to English."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram import Update

_DIR = Path(__file__).parent
_CATALOG: dict[str, dict[str, str]] = {}  # lang -> {dotted.key -> text}


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in data.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = str(v)
    return out


def _load() -> None:
    for f in sorted(_DIR.glob("*.toml")):
        with open(f, "rb") as fh:
            _CATALOG[f.stem] = _flatten(tomllib.load(fh))


_load()


def t(key: str, lang: str = "en", **kwargs: object) -> str:
    """Get a translated string. Falls back to English, then to the key itself."""
    text = _CATALOG.get(lang, {}).get(key) or _CATALOG.get("en", {}).get(key, key)
    return text.format(**kwargs) if kwargs else text


def lang(update: Update) -> str:
    """Get language: ChatConfig override > Telegram user language_code > 'en'."""
    from reverse_image_search_bot.config import ChatConfig

    chat = update.effective_chat
    if chat:
        cfg = ChatConfig(chat.id)
        if cfg.language:
            return cfg.language
    code = ""
    if update.effective_user:
        code = update.effective_user.language_code or ""
    base = code.split("-")[0]
    return base if base in _CATALOG else "en"


def available_languages() -> list[str]:
    """Return sorted list of available language codes."""
    return sorted(_CATALOG.keys())
