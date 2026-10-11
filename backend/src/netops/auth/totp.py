"""TOTP (RFC 6238: SHA-1, 6 digits, 30 s) and single-use recovery codes.

A code is accepted for the current time step and one step either side (clock drift), and
only for a step later than the last one used, so an observed code cannot be replayed.
Recovery codes are random (about 50 bits each), so a plain sha256 is enough to store them.
"""

import hashlib
import hmac
import secrets
from datetime import datetime

import pyotp
import segno

STEP_SECONDS = 30
DIGITS = 6
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i
_RECOVERY_LENGTH = 10


def new_secret() -> str:
    """A random base32 secret (160 bits)."""
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def qr_svg_data_uri(uri: str) -> str:
    """The otpauth URI as a QR code (SVG data URI), drawn here so no third party sees it."""
    return str(segno.make(uri, error="m").svg_data_uri(scale=5, border=2))


def verify(secret: str, code: str, at: datetime, last_used_step: int | None) -> int | None:
    """The time step ``code`` belongs to, or None if it is wrong or already used."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    totp = pyotp.TOTP(secret, digits=DIGITS, interval=STEP_SECONDS)
    now_step = int(at.timestamp()) // STEP_SECONDS
    for step in (now_step - 1, now_step, now_step + 1):
        expected = totp.at(step * STEP_SECONDS)
        if hmac.compare_digest(expected, code) and (
            last_used_step is None or step > last_used_step
        ):
            return step
    return None


def new_recovery_codes() -> list[str]:
    """Ten codes like ``k7mfp-2wq9x``, shown to the user once."""
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_LENGTH))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    normalized = code.strip().lower().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalized.encode()).hexdigest()
