"""Authentication (M7): sign-in, sessions and the signed-in user's own account.

Public: login, MFA verification and refresh (they are how a client gets a token). Every
other route here needs ``profile:self``, which every role has and which stays open while
a session must change its password or enroll in MFA.

The refresh token travels only in an HttpOnly, SameSite=Strict cookie scoped to
/api/v1/auth (Secure over HTTPS), so page scripts never see it; the access token is
returned in the body and kept in memory by the frontend.
"""

from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy import select

from netops.api.problems import (
    RATE_LIMITED,
    VALIDATION_ERROR,
    WEAK_PASSWORD,
    ProblemError,
    ValidationIssue,
    problems,
)
from netops.api.schemas.auth import (
    AccessToken,
    CurrentUser,
    LoginRequest,
    LoginResponse,
    MfaCode,
    MfaDisable,
    MfaEnrollment,
    MfaVerifyRequest,
    PasswordChange,
    RecoveryCodes,
    SessionInfo,
    SessionPage,
)
from netops.api.security import CurrentPrincipal, Principal, client_of, guard
from netops.api.v1.common import Session
from netops.auth import service
from netops.auth.ratelimit import RateLimiter, get_rate_limiter
from netops.auth.rbac import Permission, permissions_of
from netops.auth.service import (
    AuthenticationFailedError,
    ConflictError,
    InvalidCodeError,
    IssuedSession,
    MfaChallenge,
    PasswordRejectedError,
    RateLimitedError,
)
from netops.core.settings import Settings, get_settings
from netops.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"], responses=problems(422))

REFRESH_COOKIE = "netops_refresh"
COOKIE_PATH = "/api/v1/auth"
Limiter = Annotated[RateLimiter, Depends(get_rate_limiter)]
RefreshCookie = Annotated[
    str | None,
    Cookie(
        alias=REFRESH_COOKIE,
        description="Set by login, MFA verification and refresh (HttpOnly; never readable "
        "by scripts).",
    ),
]


def _secure(request: Request, settings: Settings) -> bool:
    if settings.auth_cookie_secure == "auto":
        return request.url.scheme == "https"
    return settings.auth_cookie_secure == "true"


def _set_refresh_cookie(
    request: Request, response: Response, issued: IssuedSession, settings: Settings
) -> None:
    max_age = int((issued.refresh_expires_at - service.utcnow()).total_seconds())
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        max_age=max(max_age, 1),
        path=COOKIE_PATH,
        secure=_secure(request, settings),
        httponly=True,
        samesite="strict",
    )


def _clear_refresh_cookie(request: Request, response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=COOKIE_PATH,
        secure=_secure(request, settings),
        httponly=True,
        samesite="strict",
    )


def _failed(error: AuthenticationFailedError) -> ProblemError:
    return ProblemError(HTTPStatus.UNAUTHORIZED, detail=error.detail)


def _rate_limited(error: RateLimitedError) -> ProblemError:
    return ProblemError(
        HTTPStatus.TOO_MANY_REQUESTS,
        detail=f"Too many attempts from this address; try again in {error.retry_after} s.",
        type_=RATE_LIMITED,
        headers={"Retry-After": str(error.retry_after)},
    )


def weak_password(error: PasswordRejectedError, field: str) -> ProblemError:
    return ProblemError(
        HTTPStatus.UNPROCESSABLE_ENTITY,
        detail="The password does not meet the policy; see errors.",
        type_=WEAK_PASSWORD,
        errors=[
            ValidationIssue(loc=["body", field], msg=v.message, type=f"password.{v.code}")
            for v in error.violations
        ],
    )


def _token(issued: IssuedSession) -> AccessToken:
    return AccessToken(
        access_token=issued.access_token,
        token_type="bearer",  # noqa: S106 - the OAuth token type, not a secret
        expires_in=issued.expires_in,
        requirements=list(issued.requirements),
    )


async def _user(session: Session, principal: Principal) -> User:
    user = await session.scalar(select(User).where(User.id == principal.user_id).with_for_update())
    if user is None:  # deleted between authentication and here
        raise ProblemError(HTTPStatus.UNAUTHORIZED, detail="The session has ended.")
    return user


# --- public: getting a token ----------------------------------------------------------------


@router.post("/login", responses=problems(401, 429))
async def login(
    request: Request, response: Response, session: Session, limiter: Limiter, body: LoginRequest
) -> LoginResponse:
    """Sign in with username and password. With MFA enabled the answer is
    ``mfa_required`` and a challenge for POST /auth/mfa/verify. Every failure (unknown
    user, wrong password, locked or deactivated account) gets the same 401."""
    settings = get_settings()
    try:
        outcome = await service.login(
            session,
            body.username,
            body.password.get_secret_value(),
            client_of(request),
            settings,
            limiter,
        )
    except AuthenticationFailedError as exc:
        raise _failed(exc) from None
    except RateLimitedError as exc:
        raise _rate_limited(exc) from None
    if isinstance(outcome, MfaChallenge):
        return LoginResponse(
            status="mfa_required", mfa_challenge=outcome.challenge, expires_in=outcome.expires_in
        )
    _set_refresh_cookie(request, response, outcome, settings)
    return LoginResponse(
        status="authenticated",
        access_token=outcome.access_token,
        token_type="bearer",  # noqa: S106 - the OAuth token type, not a secret
        expires_in=outcome.expires_in,
        requirements=list(outcome.requirements),
    )


@router.post("/mfa/verify", responses=problems(401, 429))
async def verify_mfa(
    request: Request,
    response: Response,
    session: Session,
    limiter: Limiter,
    body: MfaVerifyRequest,
) -> AccessToken:
    """Complete a sign-in with a TOTP code or a recovery code (each usable once).
    Failures count towards the account lockout."""
    settings = get_settings()
    try:
        issued = await service.verify_mfa(
            session,
            body.mfa_challenge,
            body.code,
            body.recovery_code,
            client_of(request),
            settings,
            limiter,
        )
    except AuthenticationFailedError as exc:
        raise _failed(exc) from None
    except RateLimitedError as exc:
        raise _rate_limited(exc) from None
    _set_refresh_cookie(request, response, issued, settings)
    return _token(issued)


@router.post("/refresh", responses=problems(401))
async def refresh(
    request: Request, response: Response, session: Session, refresh_token: RefreshCookie = None
) -> AccessToken:
    """A new access token for the refresh cookie, which is rotated. Presenting a refresh
    token that was already used ends the whole session (and is audited)."""
    settings = get_settings()
    if not refresh_token:
        raise ProblemError(HTTPStatus.UNAUTHORIZED, detail="Not signed in.")
    try:
        issued = await service.refresh(session, refresh_token, client_of(request), settings)
    except AuthenticationFailedError as exc:
        _clear_refresh_cookie(request, response, settings)
        raise ProblemError(
            HTTPStatus.UNAUTHORIZED,
            detail=exc.detail,
            headers={"Set-Cookie": response.headers["set-cookie"]},
        ) from None
    _set_refresh_cookie(request, response, issued, settings)
    return _token(issued)


# --- the signed-in user ---------------------------------------------------------------------


@router.post(
    "/logout",
    status_code=HTTPStatus.NO_CONTENT,
    responses=problems(401, 403),
    **guard(Permission.PROFILE),
)
async def logout(
    request: Request, response: Response, session: Session, principal: CurrentPrincipal
) -> None:
    """End this session: its refresh tokens are revoked and the cookie cleared."""
    await service.logout(session, principal.user_id, principal.session_id, principal.client)
    _clear_refresh_cookie(request, response, get_settings())


@router.get("/me", responses=problems(401, 403), **guard(Permission.PROFILE))
async def get_current_user(session: Session, principal: CurrentPrincipal) -> CurrentUser:
    """The signed-in user, the permissions of their role and what the session must do
    first (``requirements``)."""
    user = await _user(session, principal)
    settings = get_settings()
    return CurrentUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        permissions=sorted(permissions_of(user.role)),
        mfa_enabled=user.mfa_enabled,
        mfa_required=service.mfa_required(user, settings),
        requirements=list(service.requirements_of(user, settings)),
        session_id=principal.session_id,
        last_login_at=user.last_login_at,
        password_changed_at=user.password_changed_at,
    )


@router.post(
    "/password",
    status_code=HTTPStatus.NO_CONTENT,
    responses=problems(401, 403),
    **guard(Permission.PROFILE),
)
async def change_password(
    session: Session, principal: CurrentPrincipal, body: PasswordChange
) -> None:
    """Change the own password (the current one is required). Every other session of the
    user ends."""
    user = await _user(session, principal)
    try:
        await service.change_password(
            session,
            user,
            body.current_password.get_secret_value(),
            body.new_password.get_secret_value(),
            principal.session_id,
            principal.client,
            get_settings(),
        )
    except AuthenticationFailedError as exc:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=exc.detail,
            type_=VALIDATION_ERROR,
            errors=[
                ValidationIssue(
                    loc=["body", "current_password"], msg=exc.detail, type="password.wrong"
                )
            ],
        ) from None
    except PasswordRejectedError as exc:
        raise weak_password(exc, "new_password") from None


@router.post("/mfa/enroll", responses=problems(401, 403, 409), **guard(Permission.PROFILE))
async def begin_mfa_enrollment(session: Session, principal: CurrentPrincipal) -> MfaEnrollment:
    """Start TOTP enrollment: a new secret (as text, otpauth URI and QR code). MFA is on
    only after POST /auth/mfa/enroll/confirm."""
    user = await _user(session, principal)
    try:
        enrollment = await service.begin_enrollment(session, user, get_settings())
    except ConflictError as exc:
        raise ProblemError(HTTPStatus.CONFLICT, detail=str(exc)) from None
    return MfaEnrollment.model_validate(enrollment)


@router.post("/mfa/enroll/confirm", responses=problems(401, 403, 409), **guard(Permission.PROFILE))
async def confirm_mfa_enrollment(
    session: Session, principal: CurrentPrincipal, body: MfaCode
) -> RecoveryCodes:
    """Turn MFA on with a code from the authenticator. Returns ten single-use recovery
    codes; they are shown only now."""
    user = await _user(session, principal)
    try:
        codes = await service.confirm_enrollment(session, user, body.code, principal.client)
    except ConflictError as exc:
        raise ProblemError(HTTPStatus.CONFLICT, detail=str(exc)) from None
    except InvalidCodeError as exc:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=str(exc),
            type_=VALIDATION_ERROR,
            errors=[ValidationIssue(loc=["body", "code"], msg=str(exc), type="mfa.wrong_code")],
        ) from None
    return RecoveryCodes(recovery_codes=codes)


@router.post(
    "/mfa/disable",
    status_code=HTTPStatus.NO_CONTENT,
    responses=problems(401, 403, 409),
    **guard(Permission.PROFILE),
)
async def disable_mfa(session: Session, principal: CurrentPrincipal, body: MfaDisable) -> None:
    """Turn MFA off (password and a code needed). Where the policy requires MFA for the
    role, the session can then only enroll again."""
    user = await _user(session, principal)
    try:
        await service.disable_mfa(
            session,
            user,
            body.password.get_secret_value(),
            body.code,
            body.recovery_code,
            principal.client,
            get_settings(),
        )
    except ConflictError as exc:
        raise ProblemError(HTTPStatus.CONFLICT, detail=str(exc)) from None
    except AuthenticationFailedError as exc:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY, detail=exc.detail, type_=VALIDATION_ERROR
        ) from None


@router.get("/sessions", responses=problems(401, 403), **guard(Permission.PROFILE))
async def list_sessions(session: Session, principal: CurrentPrincipal) -> SessionPage:
    """The user's own active sessions (sign-ins that can still be refreshed)."""
    sessions = await service.active_sessions(session, principal.user_id)
    items = [
        SessionInfo(
            id=s.id,
            started_at=s.started_at,
            last_used_at=s.last_used_at,
            expires_at=s.expires_at,
            ip=s.ip,  # type: ignore[arg-type]  # pydantic parses the address string
            user_agent=s.user_agent,
            current=s.id == principal.session_id,
        )
        for s in sessions
    ]
    return SessionPage(items=items, total=len(items), limit=max(len(items), 1), offset=0)


@router.delete(
    "/sessions/{session_id}",
    status_code=HTTPStatus.NO_CONTENT,
    responses=problems(401, 403, 404),
    **guard(Permission.PROFILE),
)
async def revoke_session(
    request: Request,
    response: Response,
    session: Session,
    principal: CurrentPrincipal,
    session_id: UUID,
) -> None:
    """End one of the own sessions (e.g. a forgotten browser elsewhere)."""
    if not await service.revoke_own_session(
        session, principal.user_id, session_id, principal.client
    ):
        raise ProblemError(HTTPStatus.NOT_FOUND, detail=f"No session {session_id}.")
    if session_id == principal.session_id:
        _clear_refresh_cookie(request, response, get_settings())
