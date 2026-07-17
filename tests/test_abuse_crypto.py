"""Tests for the abuse-report crypto (P1 AES-GCM, P2 hashing)."""

from __future__ import annotations

import pytest

from reverse_image_search_bot.abuse_report import crypto


def test_encrypt_decrypt_roundtrip():
    key = crypto.derive_key("hunter2")
    data = b"\x89PNG\r\n\x1a\n some binary image bytes \x00\xff"
    nonce, ct = crypto.encrypt_file(data, key)
    assert ct != data
    assert crypto.decrypt_file(nonce, ct, key) == data


def test_wrong_key_fails():
    from cryptography.exceptions import InvalidTag

    nonce, ct = crypto.encrypt_file(b"secret", crypto.derive_key("right"))
    with pytest.raises(InvalidTag):
        crypto.decrypt_file(nonce, ct, crypto.derive_key("wrong"))


def test_derive_key_deterministic():
    assert crypto.derive_key("abc") == crypto.derive_key("abc")
    assert crypto.derive_key("abc") != crypto.derive_key("abd")
    assert len(crypto.derive_key("abc")) == crypto.KEY_LEN


def test_page_secret_hash_verify():
    stored = crypto.hash_page_secret("s3cret")
    assert "$" in stored
    assert crypto.verify_page_secret("s3cret", stored)
    assert not crypto.verify_page_secret("wrong", stored)
    assert not crypto.verify_page_secret("s3cret", "garbage-no-dollar")


def test_gen_password_unique():
    assert crypto.gen_password() != crypto.gen_password()
    assert len(crypto.gen_report_uuid()) > 10


def test_sha256_hex():
    assert crypto.sha256_hex(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
