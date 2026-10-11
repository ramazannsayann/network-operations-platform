"""Authentication and authorization of API requests (M7, ADR-0008).

Every route except health, login, MFA verification and refresh is declared with
``guard(Permission.X)``: a dependency that authenticates the bearer token, loads the user
and checks the permission, plus an ``x-required-permission`` entry in the contract. A test
fails for a route without one.

Per request the user and the session are read from the database: a deactivated user, an
ended session (logout, revoked, reused refresh token) or a changed role takes effect at
once, not when the 15-minute access token expires. While a session must change its
password or enroll in MFA, only ``profile:self`` routes are open to it.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from ipaddress import ip_address
from typing import Annotated, Any

from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import exists, select

from netops.api.problems import (
    FORBIDDEN,
    MFA_ENROLLMENT_REQUIRED,
    PASSWORD_CHANGE_REQUIRED,
    ProblemError,
)
from netops.api.v1.common import Session
from netops.auth import audit, tokens
from netops.auth.rbac import Permission, permissions_of
from netops.auth.service import Client, Requirement, requirements_of, utcnow
from netops.core.settings import get_settings
from netops.db.enums import AuditOutcome, UserRole
from netops.db.models import RefreshToken, User

bearer_scheme = HTTPBearer(
    scheme_name="bearerAuth",
    bearerFormat="JWT",
    description="Access token from POST /api/v1/auth/login (or /auth/mfa/verify, "
    "/auth/refresh), sent as `Authorization: Bearer <token>`; valid for 15 minutes.",
    auto_error=False,
)

PERMISSION_EXTENSION = "x-required-permission"
_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class Principal:
    """The signed-in user of a request."""

    user_id: uuid.UUID
    username: str
    role: UserRole
    session_id: uuid.UUID
    requirements: tuple[Requirement, ...]
    ip: str | None
    user_agent: str | None

    @property
    def permissions(self) -> frozenset[Permission]:
        return permissions_of(self.role)

    @property
    def client(self) -> Client:
        return Client(self.ip, self.user_agent)


def client_of(request: Request) -> Client:
    """Address (as uvicorn's proxy-header handling reports it) and user agent."""
    host = request.client.host if request.client else None
    try:
        ip = str(ip_address(host)) if host else None
    except ValueError:
        ip = None
    return Client(ip, request.headers.get("user-agent"))


def _unauthorized(detail: str) -> ProblemError:
    return ProblemError(HTTPStatus.UNAUTHORIZED, detail=detail, headers=_UNAUTHORIZED_HEADERS)


async def get_principal(
    request: Request,
    session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Sign in first: this endpoint needs a bearer token.")
    settings = get_settings()
    try:
        claims = tokens.decode(credentials.credentials, tokens.ACCESS, settings)
    except tokens.InvalidTokenError:
        raise _unauthorized("The access token is invalid or has expired.") from None
    now: datetime = utcnow()
    session_active = exists().where(
        RefreshToken.family_id == claims.session_id,
        RefreshToken.user_id == claims.user_id,
        RefreshToken.revoked_at.is_(None),
        RefreshToken.expires_at > now,
    )
    row = (
        await session.execute(
            select(User, session_active.label("active")).where(User.id == claims.user_id)
        )
    ).first()
    if row is None or not row.User.is_active or not row.active:
        raise _unauthorized("The session has ended; sign in again.")
    user: User = row.User
    client = client_of(request)
    assert claims.session_id is not None  # noqa: S101 - decode() guarantees it for access tokens
    return Principal(
        user_id=user.id,
        username=user.username,
        role=user.role,
        session_id=claims.session_id,
        requirements=requirements_of(user, settings),
        ip=client.ip,
        user_agent=client.user_agent,
    )


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


async def audit_denied(
    principal: Principal, request: Request, permission: Permission, reason: str
) -> None:
    # The route's path template ("/api/v1/users/{user_id}"), not the concrete ids.
    path = request.url.path
    for name, value in request.path_params.items():
        path = path.replace(str(value), f"{{{name}}}")
    await audit.record_now(
        "access.denied",
        AuditOutcome.DENIED,
        actor_user_id=principal.user_id,
        actor_ip=principal.ip,
        target_type="route",
        target_id=f"{request.method} {path}",
        details={"permission": permission.value, "role": principal.role.value, "reason": reason},
    )


class RequirePermission:
    """Dependency: the request's principal, if its role has ``permission``."""

    def __init__(self, permission: Permission) -> None:
        self.permission = permission

    def __repr__(self) -> str:
        return f"RequirePermission({self.permission.value!r})"

    async def __call__(self, request: Request, principal: CurrentPrincipal) -> Principal:
        if principal.requirements and self.permission is not Permission.PROFILE:
            pending = principal.requirements[0]
            await audit_denied(principal, request, self.permission, pending.value)
            if pending is Requirement.PASSWORD_CHANGE:
                raise ProblemError(
                    HTTPStatus.FORBIDDEN,
                    detail="Change your password before using the platform.",
                    type_=PASSWORD_CHANGE_REQUIRED,
                )
            raise ProblemError(
                HTTPStatus.FORBIDDEN,
                detail="Set up two-factor authentication (TOTP) before using the platform.",
                type_=MFA_ENROLLMENT_REQUIRED,
            )
        if self.permission not in principal.permissions:
            await audit_denied(principal, request, self.permission, "missing_permission")
            raise ProblemError(
                HTTPStatus.FORBIDDEN,
                detail=f"Your role ({principal.role.value}) does not have the permission "
                f"{self.permission.value}.",
                type_=FORBIDDEN,
            )
        return principal


def guard(permission: Permission) -> dict[str, Any]:
    """Route decorator arguments that enforce ``permission`` and document it::

    @router.get("/devices", **guard(Permission.DEVICES_READ))
    """
    return {
        "dependencies": [Depends(RequirePermission(permission))],
        "openapi_extra": {PERMISSION_EXTENSION: permission.value},
    }
