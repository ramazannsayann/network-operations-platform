"""User administration (admins through the API, the operator through the CLI).

Every change is audited with the acting admin (``actor``; None for the CLI). The last
active admin cannot be demoted or deactivated, so the platform cannot lock itself out.
"""

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from netops.auth import audit, passwords
from netops.auth.service import (
    Client,
    ConflictError,
    PasswordRejectedError,
    clear_mfa,
    revoke_user_sessions,
    utcnow,
)
from netops.db.enums import AuditOutcome, UserRole
from netops.db.models import User

USERNAME = re.compile(r"^[a-z0-9][a-z0-9._@-]{2,63}$")


class InvalidUsernameError(ValueError):
    pass


@dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID | None  # None: the CLI on the server
    ip: str | None

    @property
    def client(self) -> Client:
        return Client(self.ip, None)

    def audit_values(self, target: User) -> dict[str, Any]:
        return {
            "actor_user_id": self.user_id,
            "actor_ip": self.ip,
            "target_type": "user",
            "target_id": target.id,
        }


CLI = Actor(user_id=None, ip=None)


def normalize_username(username: str) -> str:
    name = username.strip().lower()
    if not USERNAME.match(name):
        raise InvalidUsernameError(
            "3-64 characters: letters, digits and . _ @ - (starting with a letter or digit)"
        )
    return name


async def active_admins(session: AsyncSession) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
    )
    return int(count or 0)


async def create_user(
    session: AsyncSession,
    actor: Actor,
    *,
    username: str,
    display_name: str,
    email: str | None,
    role: UserRole,
    password: str,
    must_change_password: bool = True,
) -> User:
    name = normalize_username(username)
    if await session.scalar(select(User.id).where(User.username == name)) is not None:
        raise ConflictError(f"A user named {name!r} already exists.")
    violations = passwords.check_policy(password, username=name, names=(display_name, email))
    if violations:
        raise PasswordRejectedError(violations)
    user = User(
        id=uuid.uuid4(),
        username=name,
        display_name=display_name.strip() or name,
        email=email.strip() if email else None,
        role=role,
        password_hash=passwords.hash_password(password),
        must_change_password=must_change_password,
    )
    session.add(user)
    audit.record(
        session,
        "user.create",
        AuditOutcome.SUCCESS,
        **actor.audit_values(user),
        details={"username": name, "role": role.value, "via": "api" if actor.user_id else "cli"},
    )
    await session.commit()
    return user


async def _guard_last_admin(
    session: AsyncSession, user: User, role: UserRole, active: bool
) -> None:
    losing_admin = (
        user.role is UserRole.ADMIN
        and user.is_active
        and (role is not UserRole.ADMIN or not active)
    )
    if losing_admin and await active_admins(session) <= 1:
        raise ConflictError("This is the last active admin; make another user admin first.")


async def update_user(
    session: AsyncSession,
    actor: Actor,
    user: User,
    *,
    display_name: str | None = None,
    email: str | None = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
) -> User:
    new_role = role if role is not None else user.role
    new_active = is_active if is_active is not None else user.is_active
    await _guard_last_admin(session, user, new_role, new_active)
    changed: list[str] = []
    details: dict[str, Any] = {}
    if display_name is not None and display_name.strip() != user.display_name:
        user.display_name = display_name.strip()
        changed.append("display_name")
    if email is not None and (email.strip() or None) != user.email:
        user.email = email.strip() or None
        changed.append("email")
    if new_role is not user.role:
        details |= {"old_role": user.role.value, "new_role": new_role.value}
        user.role = new_role
        changed.append("role")
    if new_active != user.is_active:
        user.is_active = new_active
        changed.append("is_active")
        if not new_active:
            details["sessions_ended"] = await revoke_user_sessions(session, user.id, utcnow())
    if changed:
        action = "user.deactivate" if changed == ["is_active"] and not new_active else "user.update"
        audit.record(
            session,
            action,
            AuditOutcome.SUCCESS,
            **actor.audit_values(user),
            details={"fields": changed, **details},
        )
    await session.commit()
    return user


async def reset_password(
    session: AsyncSession, actor: Actor, user: User, temporary_password: str | None
) -> None:
    """Force a password change at the next sign-in, optionally setting a temporary
    password first (for a user who forgot theirs); ends the user's sessions."""
    if temporary_password is not None:
        violations = passwords.check_policy(
            temporary_password, username=user.username, names=(user.display_name, user.email)
        )
        if violations:
            raise PasswordRejectedError(violations)
        user.password_hash = passwords.hash_password(temporary_password)
        user.password_changed_at = utcnow()
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    ended = await revoke_user_sessions(session, user.id, utcnow())
    audit.record(
        session,
        "user.password_reset",
        AuditOutcome.SUCCESS,
        **actor.audit_values(user),
        details={"temporary_password_set": temporary_password is not None, "sessions_ended": ended},
    )
    await session.commit()


async def reset_mfa(session: AsyncSession, actor: Actor, user: User) -> None:
    """Remove the user's authenticator and recovery codes (lost phone); ends their
    sessions. Where policy requires MFA they enroll again at the next sign-in."""
    await clear_mfa(session, user)
    ended = await revoke_user_sessions(session, user.id, utcnow())
    audit.record(
        session,
        "auth.mfa.reset",
        AuditOutcome.SUCCESS,
        **actor.audit_values(user),
        details={"sessions_ended": ended},
    )
    await session.commit()


async def unlock(session: AsyncSession, actor: Actor, user: User) -> None:
    user.failed_login_count = 0
    user.locked_until = None
    audit.record(session, "user.unlock", AuditOutcome.SUCCESS, **actor.audit_values(user))
    await session.commit()
