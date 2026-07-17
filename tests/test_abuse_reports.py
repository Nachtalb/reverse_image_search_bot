"""Tests for reports/blobs DB layer and initData validation."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import time
from urllib.parse import urlencode

import pytest


@pytest.fixture
def abuse(tmp_path, monkeypatch):
    import reverse_image_search_bot.settings as settings

    db_path = tmp_path / "abuse.db"
    monkeypatch.setattr(settings, "ABUSE_DB_PATH", db_path)
    import reverse_image_search_bot.config.abuse as ab

    ab._local.__dict__.clear()
    ab._all_connections.clear()
    importlib.reload(ab)
    monkeypatch.setattr(ab, "ABUSE_DB_PATH", db_path)
    ab._local.__dict__.clear()
    ab._all_connections.clear()
    return ab


def test_report_lifecycle(abuse):
    abuse.record_user(1, username="bad")
    abuse.create_report("uuid1", 1, "salt$hash")
    rep = abuse.get_report("uuid1")
    assert rep["status"] == abuse.REPORT_PREPARING
    assert rep["user_id"] == 1

    abuse.add_report_blob(
        "uuid1", file_unique_id="F1", saved_filename="F1.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="abc"
    )
    abuse.add_report_blob(
        "uuid1", file_unique_id="F2", saved_filename="F2.jpg", nonce=b"n", ciphertext=b"c2", plaintext_sha256="def"
    )
    assert len(abuse.blob_meta("uuid1")) == 2

    abuse.set_report_status("uuid1", abuse.REPORT_READY)
    assert abuse.get_report("uuid1")["status"] == abuse.REPORT_READY


def test_blob_selection_and_classification(abuse):
    abuse.record_user(1)
    abuse.create_report("u", 1, "h")
    abuse.add_report_blob(
        "u", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    abuse.add_report_blob(
        "u", file_unique_id="B", saved_filename="B.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="2"
    )
    meta = abuse.blob_meta("u")
    ids = [m["id"] for m in meta]

    abuse.set_blob_selection("u", {ids[0]: "A1"})
    sel = abuse.report_blobs("u", selected_only=True)
    assert len(sel) == 1
    assert sel[0]["classification"] == "A1"

    # Re-select replaces prior selection entirely.
    abuse.set_blob_selection("u", {ids[1]: "B2"})
    sel = abuse.report_blobs("u", selected_only=True)
    assert len(sel) == 1
    assert sel[0]["file_unique_id"] == "B"
    assert sel[0]["classification"] == "B2"


def test_ncmec_id_and_filed(abuse):
    abuse.record_user(9)
    abuse.create_report("r", 9, "h")
    abuse.set_report_ncmec_id("r", 555111)
    assert abuse.get_report("r")["ncmec_report_id"] == 555111
    assert not abuse.has_report(9)
    abuse.mark_report_filed("r")
    assert abuse.get_report("r")["status"] == abuse.REPORT_FILED
    assert abuse.has_report(9)  # 🚩 lights up


def test_purge_blobs(abuse):
    abuse.record_user(1)
    abuse.create_report("p", 1, "h")
    abuse.add_report_blob(
        "p", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    assert abuse.purge_report_blobs("p") == 1
    assert abuse.blob_meta("p") == []


def test_active_report_for_user(abuse):
    abuse.record_user(1)
    abuse.create_report("act", 1, "h")
    abuse.set_report_status("act", abuse.REPORT_READY)
    assert abuse.active_report_for_user(1)["report_uuid"] == "act"
    abuse.set_report_status("act", abuse.REPORT_FILED)
    assert abuse.active_report_for_user(1) is None  # terminal → not active


def test_get_blob_cipher(abuse):
    abuse.record_user(1)
    abuse.create_report("g", 1, "h")
    abuse.add_report_blob(
        "g", file_unique_id="A", saved_filename="A.jpg", nonce=b"NONCE", ciphertext=b"CIPHER", plaintext_sha256="1"
    )
    bid = abuse.blob_meta("g")[0]["id"]
    row = abuse.get_blob_cipher("g", bid)
    assert bytes(row["nonce"]) == b"NONCE"
    assert bytes(row["ciphertext"]) == b"CIPHER"


# --- initData validation ------------------------------------------------------


def _signed_init_data(bot_token: str, user_json: str, auth_date: int | None = None) -> str:
    auth_date = auth_date if auth_date is not None else int(time.time())
    params = {"user": user_json, "auth_date": str(auth_date), "query_id": "AAA"}
    check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    params["hash"] = h
    return urlencode(params)


def test_verify_init_data_valid():
    from reverse_image_search_bot.abuse_report.server import verify_init_data

    token = "123:abc"
    init = _signed_init_data(token, '{"id":42,"username":"a"}')
    user = verify_init_data(init, token)
    assert user and user["id"] == 42


def test_verify_init_data_bad_hash():
    from reverse_image_search_bot.abuse_report.server import verify_init_data

    init = _signed_init_data("123:abc", '{"id":42}')
    assert verify_init_data(init, "999:wrong") is None


def test_verify_init_data_expired():
    from reverse_image_search_bot.abuse_report.server import verify_init_data

    token = "123:abc"
    init = _signed_init_data(token, '{"id":42}', auth_date=int(time.time()) - 99999)
    assert verify_init_data(init, token, max_age=3600) is None


def test_verify_init_data_empty():
    from reverse_image_search_bot.abuse_report.server import verify_init_data

    assert verify_init_data("", "123:abc") is None
