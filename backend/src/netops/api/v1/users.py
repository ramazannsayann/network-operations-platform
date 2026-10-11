"""User administration (M7): admins only (``users:manage``)."""

from http import HTTPStatus
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from netops.api.problems import VALIDATION_ERROR, ProblemError, ValidationIssue, problems
from netops.api.schemas.users import PasswordReset, User, UserCreate, UserPage, UserUpdate
from netops.api.security import CurrentPrincipal, Principal, guard
from netops.api.v1.auth import weak_password
from netops.api.v1.common import DEFAULT_LIMIT, Limit, Offset, SearchText, Session
from netops.auth import users
from netops.auth.rbac import Permission
from netops.auth.service import ConflictError, PasswordRejectedError
from netops.db import models as m
from netops.db.enums import UserRole

router = APIRouter(prefix="/users", tags=["users"], responses=problems(401, 403, 422))

UserSort = Literal["username", "-username", "last_login_at", "-last_login_at"]
_MANAGE = guard(Permission.USERS_MANAGE)


def _actor(principal: Principal) -> users.Actor:
    return users.Actor(user_id=principal.user_id, ip=principal.ip)


async def _target(session: Session, user_id: UUID) -> m.User:
    user = await session.scalar(select(m.User).where(m.User.id == user_id).with_for_update())
    if user is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, detail=f"User {user_id} does not exist.")
    return user


@router.get("", **_MANAGE)
async def list_users(
    session: Session,
    q: SearchText = None,
    role: Annotated[list[UserRole] | None, Query()] = None,
    is_active: bool | None = None,
    sort: UserSort = "username",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> UserPage:
    """Users; ``q`` searches username, display name and email."""
    conditions = []
    if q:
        pattern = f"%{q}%"
        conditions.append(
            or_(
                m.User.username.ilike(pattern),
                m.User.display_name.ilike(pattern),
                m.User.email.ilike(pattern),
            )
        )
    if role:
        conditions.append(m.User.role.in_(role))
    if is_active is not None:
        conditions.append(m.User.is_active.is_(is_active))
    total = await session.scalar(select(func.count()).select_from(m.User).where(*conditions))
    column = m.User.last_login_at if "last_login_at" in sort else m.User.username
    order = column.desc().nulls_last() if sort.startswith("-") else column.asc().nulls_last()
    rows = await session.scalars(
        select(m.User)
        .where(*conditions)
        .order_by(order, m.User.username)
        .limit(limit)
        .offset(offset)
    )
    return UserPage(
        items=[User.model_validate(u) for u in rows], total=total or 0, limit=limit, offset=offset
    )


@router.post("", status_code=HTTPStatus.CREATED, responses=problems(409), **_MANAGE)
async def create_user(session: Session, principal: CurrentPrincipal, body: UserCreate) -> User:
    """Create a user with a temporary password, to be changed at the first sign-in."""
    try:
        user = await users.create_user(
            session,
            _actor(principal),
            username=body.username,
            display_name=body.display_name,
            email=body.email,
            role=body.role,
            password=body.password.get_secret_value(),
        )
    except users.InvalidUsernameError as exc:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=str(exc),
            type_=VALIDATION_ERROR,
            errors=[ValidationIssue(loc=["body", "username"], msg=str(exc), type="username")],
        ) from None
    except ConflictError as exc:
        raise ProblemError(HTTPStatus.CONFLICT, detail=str(exc)) from None
    except PasswordRejectedError as exc:
        raise weak_password(exc, "password") from None
    return User.model_validate(user)


@router.get("/{user_id}", responses=problems(404), **_MANAGE)
async def get_user(session: Session, user_id: UUID) -> User:
    return User.model_validate(await _target(session, user_id))


@router.patch("/{user_id}", responses=problems(404, 409), **_MANAGE)
async def update_user(
    session: Session, principal: CurrentPrincipal, user_id: UUID, body: UserUpdate
) -> User:
    """Change display name, email, role or active state. The last active admin cannot be
    demoted or deactivated."""
    user = await _target(session, user_id)
    try:
        await users.update_user(
            session,
            _actor(principal),
            user,
            display_name=body.display_name,
            email=body.email,
            role=body.role,
            is_active=body.is_active,
        )
    except ConflictError as exc:
        raise ProblemError(HTTPStatus.CONFLICT, detail=str(exc)) from None
    return User.model_validate(user)


@router.post("/{user_id}/deactivate", responses=problems(404, 409), **_MANAGE)
async def deactivate_user(session: Session, principal: CurrentPrincipal, user_id: UUID) -> User:
    """Deactivate a user (users are never deleted) and end their sessions."""
    user = await _target(session, user_id)
    try:
        await users.update_user(session, _actor(principal), user, is_active=False)
    except ConflictError as exc:
        raise ProblemError(HTTPStatus.CONFLICT, detail=str(exc)) from None
    return User.model_validate(user)


@router.post(
    "/{user_id}/reset-mfa",
    status_code=HTTPStatus.NO_CONTENT,
    responses=problems(404),
    **_MANAGE,
)
async def reset_user_mfa(session: Session, principal: CurrentPrincipal, user_id: UUID) -> None:
    """Remove the user's authenticator and recovery codes (lost phone) and end their
    sessions; they enroll again at the next sign-in where the policy requires MFA."""
    await users.reset_mfa(session, _actor(principal), await _target(session, user_id))


@router.post(
    "/{user_id}/reset-password",
    status_code=HTTPStatus.NO_CONTENT,
    responses=problems(404),
    **_MANAGE,
)
async def reset_user_password(
    session: Session, principal: CurrentPrincipal, user_id: UUID, body: PasswordReset
) -> None:
    """Force a password change at the next sign-in, optionally setting a temporary
    password; ends the user's sessions."""
    user = await _target(session, user_id)
    temporary = body.temporary_password.get_secret_value() if body.temporary_password else None
    try:
        await users.reset_password(session, _actor(principal), user, temporary)
    except PasswordRejectedError as exc:
        raise weak_password(exc, "temporary_password") from None


@router.post(
    "/{user_id}/unlock",
    status_code=HTTPStatus.NO_CONTENT,
    responses=problems(404),
    **_MANAGE,
)
async def unlock_user(session: Session, principal: CurrentPrincipal, user_id: UUID) -> None:
    """Lift a lockout after failed sign-ins."""
    await users.unlock(session, _actor(principal), await _target(session, user_id))
