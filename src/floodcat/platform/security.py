"""Security primitives: password hashing and policy, one-time tokens, secret encryption, TOTP MFA (AUTH-07, -08, -10)."""

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from pathlib import Path
from urllib.parse import quote
from ..core.errors import ModelError

# Passwords -----------------------------------------------------------------------------------------
MIN_PASSWORD = 12
MAX_PASSWORD = 128
# A short list of the most common passwords and patterns; the breached-password check (HIBP) covers the rest.
COMMON = {
    "password",
    "password1",
    "password123",
    "123456789012",
    "qwertyuiopas",
    "iloveyou1234",
    "welcome12345",
    "admin1234567",
    "letmein12345",
    "changeme1234",
    "passw0rd1234",
    "nairobi12345",
    "kenya1234567",
    "insurance123",
    "reinsurance1",
    "qwerty123456",
    "111111111111",
    "000000000000",
    "abcdefghijkl",
    "password1234",
    "football1234",
    "sunshine1234",
}


def _hasher():
    from argon2 import PasswordHasher

    return PasswordHasher()  # Argon2id, library defaults (RFC 9106 low-memory profile)


def hash_password(password):
    return _hasher().hash(password)


def verify_password(stored, password):
    """Return (ok, needs_rehash). Accepts Argon2id and the prototype's legacy 'pbkdf2$<salt>$<hash>' format."""
    if not stored:
        return False, False
    if stored.startswith("pbkdf2$"):
        _, salt, expected = stored.split("$", 2)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), 310_000
        ).hex()
        return hmac.compare_digest(actual, expected), True
    from argon2.exceptions import (
        InvalidHashError,
        VerifyMismatchError,
        VerificationError,
    )

    try:
        _hasher().verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, False
    return True, _hasher().check_needs_rehash(stored)


def dummy_verify():
    """Spend the same time as a real check so unknown accounts cannot be detected by timing."""
    verify_password(_DUMMY, "not-the-password")


def breached_count(password, timeout=3.0):
    """Times the password appears in known breaches via the HIBP k-anonymity API (only 5 hash characters leave the server).
    Returns None when the service is unavailable or disabled (FLOODCAT_BREACH_CHECK=0)."""
    if os.getenv("FLOODCAT_BREACH_CHECK", "1") == "0":
        return None
    import httpx

    digest = hashlib.sha1(password.encode()).hexdigest().upper()
    try:
        response = httpx.get(
            f"https://api.pwnedpasswords.com/range/{digest[:5]}",
            timeout=timeout,
            headers={"Add-Padding": "true"},
        )
        response.raise_for_status()
    except Exception:
        return None
    for line in response.text.splitlines():
        suffix, _, count = line.partition(":")
        if suffix == digest[5:]:
            return int(count)
    return 0


def check_password(password, email="", extra_words=()):
    """NIST SP 800-63B style: length, not common, not the user's own details, not breached. No composition rules."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise ModelError(
            "weak_password",
            f"Use at least {MIN_PASSWORD} characters. A short sentence works well.",
        )
    if len(password) > MAX_PASSWORD:
        raise ModelError("weak_password", f"Use at most {MAX_PASSWORD} characters")
    lowered = password.lower()
    if lowered in COMMON or len(set(lowered)) < 4:
        raise ModelError("weak_password", "This password is too common or repetitive")
    for word in [email.split("@")[0] if email else "", *extra_words]:
        if word and len(word) >= 4 and word.lower() in lowered:
            raise ModelError(
                "weak_password",
                "Do not use your name, e-mail or organisation in your password",
            )
    count = breached_count(password)
    if count:
        raise ModelError(
            "breached_password",
            f"This password has appeared in {count:,} known data breaches. Choose another.",
        )
    return count is not None


# One-time tokens ----------------------------------------------------------------------------------
def new_token(nbytes=32):
    """Return (raw token for the user, SHA-256 hash for storage)."""
    raw = secrets.token_urlsafe(nbytes)
    return raw, hash_token(raw)


def hash_token(raw):
    return hashlib.sha256(str(raw).encode()).hexdigest()


# Secret encryption (TOTP seeds, SSO client secrets, stored inputs) --------------------------------------
_fernet = None


def _key():
    key = os.getenv("FLOODCAT_SECRET_KEY")
    if key:
        return key.encode()
    if os.getenv("FLOODCAT_ENV", "development") == "production":
        raise RuntimeError("Production requires FLOODCAT_SECRET_KEY (a Fernet key)")
    from cryptography.fernet import Fernet

    from .db import store_dir

    path = store_dir() / "secret.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
        path.chmod(0o600)
    return path.read_bytes()


def fernet():
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet

        _fernet = Fernet(_key())
    return _fernet


def encrypt(text):
    return fernet().encrypt(text.encode()).decode()


def decrypt(token):
    from cryptography.fernet import InvalidToken

    try:
        return fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise ModelError(
            "decryption_failed",
            "Stored secret could not be decrypted (wrong FLOODCAT_SECRET_KEY?)",
        ) from None


# TOTP (RFC 6238) ------------------------------------------------------------------------------------
TOTP_STEP = 30
TOTP_DIGITS = 6


def new_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret, at=None, step_offset=0):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = int((at if at is not None else time.time()) // TOTP_STEP) + step_offset
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (
        struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    ) % 10**TOTP_DIGITS
    return f"{code:0{TOTP_DIGITS}d}"


def verify_totp(secret, code, at=None, window=1):
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if len(code) != TOTP_DIGITS:
        return False
    return any(
        hmac.compare_digest(totp(secret, at, k), code)
        for k in range(-window, window + 1)
    )


def totp_uri(secret, email, issuer="Xpat"):
    return f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}&issuer={quote(issuer)}&digits={TOTP_DIGITS}&period={TOTP_STEP}"


def qr_svg(data):
    import io
    import segno

    buffer = io.BytesIO()
    segno.make(data, error="m").save(
        buffer, kind="svg", scale=5, dark="#111111", light="#ffffff", border=2
    )
    return buffer.getvalue().decode()


def new_recovery_codes(n=10):
    codes = ["-".join(secrets.token_hex(3) for _ in range(2)) for _ in range(n)]
    return codes, [hash_token(c) for c in codes]


_DUMMY = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHRzb21lc2FsdA$0hGt7bVq8f5b2iDkq7hU2s2Wq0p1o9n8m7l6k5j4h3g"
