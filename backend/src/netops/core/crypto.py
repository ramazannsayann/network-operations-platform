"""Encryption of stored credentials (ADR-0004).

Fernet (AES-128-CBC with an HMAC-SHA256 tag) from ``cryptography``. CREDENTIALS_KEY holds
one or more comma-separated Fernet keys: the first encrypts, all of them decrypt
(MultiFernet), so a new key can be put in front of the old one to rotate keys.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from netops.core.secrets import Secret
from netops.core.settings import get_settings

KEY_HELP = (
    "CREDENTIALS_KEY must hold one or more comma-separated Fernet keys; generate one with "
    "`openssl rand -base64 32 | tr '+/' '-_'` (make up does this for deploy/.env)."
)


class CredentialDecryptionError(Exception):
    """A stored secret could not be decrypted (wrong or rotated-out CREDENTIALS_KEY?)."""


def parse_keys(raw: str) -> list[Fernet]:
    """The Fernet keys in a CREDENTIALS_KEY value; raises ValueError if any is invalid."""
    keys = [part.strip() for part in raw.split(",") if part.strip()]
    if not keys:
        raise ValueError(KEY_HELP)
    try:
        return [Fernet(key.encode()) for key in keys]
    except ValueError:
        raise ValueError(KEY_HELP) from None


@lru_cache
def get_cipher() -> MultiFernet:
    return MultiFernet(parse_keys(get_settings().credentials_key.get_secret_value()))


def encrypt_secret(secret: Secret) -> bytes:
    return get_cipher().encrypt(secret.get_secret_value().encode())


def decrypt_secret(token: bytes) -> Secret:
    try:
        return Secret(get_cipher().decrypt(token).decode())
    except InvalidToken:
        raise CredentialDecryptionError(
            "Stored credential cannot be decrypted with the configured CREDENTIALS_KEY."
        ) from None
