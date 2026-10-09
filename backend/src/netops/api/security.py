"""Bearer-token (JWT) security scheme.

Declared now so every endpoint's OpenAPI entry carries its security requirement; tokens
are not checked yet. M7 implements validation in ``bearer_auth``.
"""

from typing import Annotated

from fastapi import Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer(
    scheme_name="bearerAuth",
    bearerFormat="JWT",
    description="JWT from POST /api/v1/auth/login, sent as `Authorization: Bearer <token>`.",
    auto_error=False,
)


async def bearer_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> None:
    """Not enforced yet: accepts requests with or without a token."""


# Router/route dependency that marks endpoints as requiring authentication.
AUTHENTICATED = [Security(bearer_auth)]
