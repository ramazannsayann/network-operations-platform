"""Access tokens and MFA challenge tokens (JWT, HS256), and refresh tokens (opaque).

JWTs carry ``iss``, ``aud``, ``sub`` (user id), ``iat``, ``exp``, ``jti`` and ``typ``
(``access`` or ``mfa_challenge``, so one cannot stand in for the other); access tokens also
carry ``sid``, the session (refresh token family). They are signed with the first key of
AUTH_SIGNING_KEY and verified with whichever key the ``kid`` header names, so keys can be
rotated like CREDENTIALS_KEY. Roles are not in the token: every request reads the user's
current role and state from the database.

Refresh tokens are random strings; only their sha256 is stored.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import jwt

from netops.core.settings import Settings

ISSUER = "netops"
AUDIENCE = "netops-api"
ACCESS = "access"
MFA_CHALLENGE = "mfa_challenge"
MFA_CHALLENGE_SECONDS = 300
_ALGORITHM = "HS256"
_LEEWAY_SECONDS = 5


class InvalidTokenError(Exception):
    """Expired, tampered with, signed with an unknown key, or of the wrong type."""


def _keys(settings: Settings) -> list[str]:
    raw = settings.auth_signing_key.get_secret_value()
    return [key.strip() for key in raw.split(",") if key.strip()]


def _kid(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _encode(claims: dict[str, Any], settings: Settings) -> str:
    key = _keys(settings)[0]
    return jwt.encode(claims, key, algorithm=_ALGORITHM, headers={"kid": _kid(key)})


def _claims(user_id: uuid.UUID, typ: str, now: datetime, lifetime: timedelta) -> dict[str, Any]:
    return {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "jti": uuid.uuid4().hex,
        "typ": typ,
    }


def issue_access_token(
    user_id: uuid.UUID, session_id: uuid.UUID, settings: Settings, now: datetime
) -> tuple[str, int]:
    """The token and its lifetime in seconds."""
    lifetime = timedelta(minutes=settings.auth_access_token_minutes)
    claims = _claims(user_id, ACCESS, now, lifetime) | {"sid": str(session_id)}
    return _encode(claims, settings), int(lifetime.total_seconds())


def issue_mfa_challenge(user_id: uuid.UUID, settings: Settings, now: datetime) -> str:
    """Proves the password was right; only POST /auth/mfa/verify accepts it."""
    return _encode(
        _claims(user_id, MFA_CHALLENGE, now, timedelta(seconds=MFA_CHALLENGE_SECONDS)), settings
    )


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID | None
    expires_at: int


def decode(token: str, typ: str, settings: Settings) -> TokenClaims:
    """Verified claims of a token of type ``typ``; raises InvalidTokenError otherwise."""
    keys = _keys(settings)
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError:
        raise InvalidTokenError("malformed token") from None
    candidates = [key for key in keys if _kid(key) == kid] or keys
    for key in candidates:
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[_ALGORITHM],
                audience=AUDIENCE,
                issuer=ISSUER,
                leeway=_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "sub", "jti", "typ"]},
            )
        except jwt.InvalidSignatureError:
            continue
        except jwt.PyJWTError:
            raise InvalidTokenError("invalid token") from None
        if claims.get("typ") != typ:
            raise InvalidTokenError("wrong token type")
        try:
            user_id = uuid.UUID(claims["sub"])
            session = uuid.UUID(claims["sid"]) if "sid" in claims else None
        except (ValueError, TypeError):
            raise InvalidTokenError("invalid subject") from None
        if typ == ACCESS and session is None:
            raise InvalidTokenError("access token without session")
        return TokenClaims(user_id=user_id, session_id=session, expires_at=int(claims["exp"]))
    raise InvalidTokenError("bad signature")


def new_refresh_token() -> tuple[str, str]:
    """A refresh token and the sha256 (hex) to store instead of it."""
    token = secrets.token_urlsafe(32)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
