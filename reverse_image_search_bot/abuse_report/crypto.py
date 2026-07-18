"""Crypto for the abuse-report pipeline.

Two secrets per report round:

- **P1** (image key): a one-time password shown to the admin ONCE and never
  stored. Files are AES-256-GCM encrypted into DB blobs with a key derived from
  P1 via PBKDF2-SHA256. The browser re-derives the same key with WebCrypto and
  decrypts locally — the server never sees plaintext again after preparation.
- **P2** (page secret): gates the report page. Stored only as a salted hash.

The KDF parameters here MUST match the browser's WebCrypto derivation exactly
(PBKDF2, SHA-256, 200k iterations, 32-byte key, 16-byte salt, 12-byte GCM nonce).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Must match the frontend constants in report.html.
PBKDF2_ITERATIONS = 200_000
KEY_LEN = 32  # AES-256
SALT_LEN = 16
NONCE_LEN = 12

# A fixed application salt for P1 key derivation. The report is short-lived and
# the ciphertext lives only in our DB behind the P2 gate + initData auth; a
# per-app salt keeps the browser derivation deterministic from P1 alone (the
# admin types only P1, no salt to carry). Rotating this invalidates old blobs,
# which is fine — blobs are purged on finish/cancel anyway.
P1_SALT = b"ris-abuse-report-p1-v1"


def gen_password(nbytes: int = 9) -> str:
    """A short, URL/DM-safe one-time password (base64url, ~12 chars for 9 bytes)."""
    return secrets.token_urlsafe(nbytes)


def gen_report_uuid() -> str:
    return secrets.token_urlsafe(16)


def derive_key(p1: str) -> bytes:
    """Derive the AES-256 key from P1. Mirrors the browser's WebCrypto PBKDF2."""
    return hashlib.pbkdf2_hmac("sha256", p1.encode("utf-8"), P1_SALT, PBKDF2_ITERATIONS, dklen=KEY_LEN)


def encrypt_file(data: bytes, key: bytes) -> tuple[bytes, bytes]:
    """AES-256-GCM encrypt. Returns (nonce, ciphertext-with-tag)."""
    nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, data, None)
    return nonce, ct


def decrypt_file(nonce: bytes, ciphertext: bytes, key: bytes) -> bytes:
    """AES-256-GCM decrypt. Raises on auth failure. (Server-side verification only.)"""
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def hash_page_secret(p2: str) -> str:
    """Salted hash of P2 for storage. ``salt$hex`` form."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", p2.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()
    return f"{salt}${digest}"


def verify_page_secret(p2: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", p2.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()
    return hmac.compare_digest(calc, digest)


def verify_global_page_password(entered: str, configured: str) -> bool:
    """Constant-time check of the typed page password against the global one.

    The page password is a single global secret (same for every report, stored
    in Proton Pass). If no global password is configured, the gate is open
    (initData admin auth still applies).
    """
    if not configured:
        return True
    return hmac.compare_digest(entered.encode("utf-8"), configured.encode("utf-8"))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
