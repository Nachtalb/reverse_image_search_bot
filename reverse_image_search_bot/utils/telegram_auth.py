"""Telegram Mini App initData verification.

Shared by every Mini App the bot serves (the admin report console and the user
search-history app), so the HMAC recipe lives in exactly one place.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def verify_init_data(init_data: str, bot_token: str, max_age: int = 3600) -> dict | None:
    """Validate Telegram Mini App initData. Returns the parsed user dict or None.

    Recipe: secret = HMAC_SHA256("WebAppData", bot_token); the check hash is
    HMAC_SHA256(secret, data_check_string) where data_check_string is the sorted
    "k=v\\n…" of all params except `hash`.
    """
    if not init_data:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    got_hash = pairs.pop("hash", None)
    if not got_hash:
        return None
    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, got_hash):
        return None
    # auth_date freshness
    try:
        if max_age and (time.time() - int(pairs.get("auth_date", "0"))) > max_age:
            return None
    except ValueError:
        return None
    try:
        return json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        return None
