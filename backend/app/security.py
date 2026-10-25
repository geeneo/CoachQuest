"""Password hashing, session tokens and encryption of provider tokens."""

import base64
import hashlib
import hmac
import json
import secrets

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

_SCRYPT = {"n": 2**15, "r": 8, "p": 1, "maxmem": 64 * 1024 * 1024, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(key).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, key_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    key = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(key, base64.b64decode(key_b64))


# A fixed hash so a login for an unknown email costs the same time as a real one.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def proxy_secret_ok(value: str | None) -> bool:
    expected = settings.proxy_shared_secret
    return bool(expected) and bool(value) and hmac.compare_digest(value, expected)


def _fernet() -> Fernet:
    return Fernet(settings.token_encryption_key.encode())


def encrypt_json(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(blob: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(blob.encode()))
    except InvalidToken as exc:
        raise RuntimeError("Could not decrypt stored token; TOKEN_ENCRYPTION_KEY changed?") from exc
