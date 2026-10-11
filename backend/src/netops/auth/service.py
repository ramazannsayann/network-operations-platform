"""Signing in and out, sessions, password changes and MFA of the signed-in user.

Functions commit themselves, because failures must be recorded (failure counters,
lockouts, audit entries) even when the request then fails.

Login failures look the same from outside whatever the reason (unknown user, wrong
password, locked or deactivated account): ``AuthenticationFailedError`` with one message, after
one argon2 computation in every case. The audit log records the real reason.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from netops.auth import audit, passwords, tokens, totp
from netops.auth.passwords import PolicyViolation
from netops.auth.ratelimit import RateLimiter
from netops.core.secrets import Secret
from netops.core.settings import Settings
from netops.db.enums import AuditOutcome
from netops.db.models import MfaRecoveryCode, RefreshToken, User

logger = logging.getLogger(__name__)

GENERIC_FAILURE = "The username or password is wrong, or the account cannot sign in now."
_AUDITED_USERNAME_LENGTH = 64


class Requirement(StrEnum):
    """What a session must do before it may use anything but its own account."""

    PASSWORD_CHANGE = "password_change"  # noqa: S105 - a requirement name
    MFA_ENROLLMENT = "mfa_enrollment"


class AuthenticationFailedError(Exception):
    def __init__(self, detail: str = GENERIC_FAILURE) -> None:
        super().__init__(detail)
        self.detail = detail


class RateLimitedError(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"retry after {retry_after} s")
        self.retry_after = retry_after


class PasswordRejectedError(Exception):
    def __init__(self, violations: list[PolicyViolation]) -> None:
        super().__init__("; ".join(v.message for v in violations))
        self.violations = violations


class ConflictError(Exception):
    """The request does not fit the account's state (409)."""


class InvalidCodeError(Exception):
    """A wrong TOTP or recovery code from a signed-in user (422)."""


@dataclass(frozen=True)
class Client:
    ip: str | None
    user_agent: str | None


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_at: datetime
    session_id: uuid.UUID
    requirements: tuple[Requirement, ...]


@dataclass(frozen=True)
class MfaChallenge:
    challenge: str
    expires_in: int


def utcnow() -> datetime:
    return datetime.now(UTC)


# --- account state --------------------------------------------------------------------------


def mfa_required(user: User, settings: Settings) -> bool:
    return user.role.value in settings.mfa_required_roles


def requirements_of(user: User, settings: Settings) -> tuple[Requirement, ...]:
    pending = []
    if user.must_change_password:
        pending.append(Requirement.PASSWORD_CHANGE)
    if mfa_required(user, settings) and not user.mfa_enabled:
        pending.append(Requirement.MFA_ENROLLMENT)
    return tuple(pending)


def is_locked(user: User, now: datetime) -> bool:
    return user.locked_until is not None and user.locked_until > now


def register_failure(
    session: AsyncSession, user: User, settings: Settings, now: datetime, client: Client
) -> None:
    """Count a wrong password or code. From the threshold on the account is locked, for
    twice as long with every further failure (up to the maximum); each lock is audited."""
    user.failed_login_count += 1
    excess = user.failed_login_count - settings.auth_lockout_threshold
    if excess < 0:
        return
    seconds = min(
        settings.auth_lockout_base_seconds * 2 ** min(excess, 30),
        settings.auth_lockout_max_seconds,
    )
    user.locked_until = now + timedelta(seconds=seconds)
    audit.record(
        session,
        "auth.lockout",
        AuditOutcome.SUCCESS,
        actor_user_id=user.id,
        actor_ip=client.ip,
        target_type="user",
        target_id=user.id,
        details={"failures": user.failed_login_count, "locked_seconds": seconds},
    )


async def _limit(limiter: RateLimiter, scope: str, settings: Settings, client: Client) -> None:
    retry = await limiter.hit(
        f"{scope}:{client.ip or 'unknown'}",
        settings.auth_rate_limit_per_ip,
        settings.auth_rate_limit_window_seconds,
    )
    if retry is not None:
        await audit.record_now(
            "auth.rate_limited",
            AuditOutcome.DENIED,
            actor_ip=client.ip,
            details={"endpoint": scope, "retry_after_seconds": retry},
        )
        raise RateLimitedError(retry)


# --- sessions (refresh token families) ------------------------------------------------------


def _new_refresh_row(
    user: User,
    family_id: uuid.UUID,
    started_at: datetime,
    settings: Settings,
    client: Client,
    now: datetime,
) -> tuple[RefreshToken, str]:
    token, token_hash = tokens.new_refresh_token()
    expires_at = min(
        now + timedelta(hours=settings.auth_refresh_token_hours),
        started_at + timedelta(days=settings.auth_session_max_days),
    )
    row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family_id,
        token_hash=token_hash,
        created_at=now,
        expires_at=expires_at,
        ip=audit.host(client.ip),
        user_agent=(client.user_agent or "")[:300] or None,
    )
    return row, token


def _issue(
    session: AsyncSession, user: User, settings: Settings, client: Client, now: datetime
) -> IssuedSession:
    family_id = uuid.uuid4()
    row, token = _new_refresh_row(user, family_id, now, settings, client, now)
    session.add(row)
    access, expires_in = tokens.issue_access_token(user.id, family_id, settings, now)
    user.last_login_at = now
    user.failed_login_count = 0
    user.locked_until = None
    return IssuedSession(
        access, expires_in, token, row.expires_at, family_id, requirements_of(user, settings)
    )


async def revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> int:
    result = await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def revoke_user_sessions(
    session: AsyncSession, user_id: uuid.UUID, now: datetime, keep: uuid.UUID | None = None
) -> int:
    conditions = [RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)]
    if keep is not None:
        conditions.append(RefreshToken.family_id != keep)
    result = await session.execute(update(RefreshToken).where(*conditions).values(revoked_at=now))
    return int(getattr(result, "rowcount", 0) or 0)


# --- login ----------------------------------------------------------------------------------


async def login(
    session: AsyncSession,
    username: str,
    password: str,
    client: Client,
    settings: Settings,
    limiter: RateLimiter,
    now: datetime | None = None,
) -> IssuedSession | MfaChallenge:
    now = now or utcnow()
    await _limit(limiter, "login", settings, client)
    name = username.strip().lower()
    user = await session.scalar(select(User).where(User.username == name).with_for_update())
    correct = passwords.verify_password(user.password_hash if user else None, password)

    def failed(reason: str, user_id: uuid.UUID | None = None) -> None:
        audit.record(
            session,
            "auth.login",
            AuditOutcome.FAILED,
            actor_user_id=user_id,
            actor_ip=client.ip,
            details={"reason": reason, "username": name[:_AUDITED_USERNAME_LENGTH]},
        )

    if user is None:
        failed("unknown_user")
    elif not user.is_active:
        failed("inactive", user.id)
    elif is_locked(user, now):
        failed("locked", user.id)
    elif not correct:
        failed("wrong_password", user.id)
        register_failure(session, user, settings, now, client)
    if user is None or not user.is_active or is_locked(user, now) or not correct:
        await session.commit()
        raise AuthenticationFailedError()

    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
    if user.mfa_enabled:
        # The failure counter is reset only after the second factor: knowing the password
        # must not buy unlimited code guesses.
        await session.commit()
        challenge = tokens.issue_mfa_challenge(user.id, settings, now)
        return MfaChallenge(challenge, tokens.MFA_CHALLENGE_SECONDS)
    issued = _issue(session, user, settings, client, now)
    details: dict[str, Any] = {"mfa": "none", "session_id": str(issued.session_id)}
    if issued.requirements:
        # Signed in, but limited to the own account until these are done.
        details["requirements"] = [r.value for r in issued.requirements]
    audit.record(
        session,
        "auth.login",
        AuditOutcome.SUCCESS,
        actor_user_id=user.id,
        actor_ip=client.ip,
        details=details,
    )
    await session.commit()
    return issued


async def _check_code(
    session: AsyncSession, user: User, code: str | None, recovery_code: str | None, now: datetime
) -> str | None:
    """Which second factor was used ("totp", "recovery_code"), or None if it was wrong.
    A used TOTP step or recovery code can never be used again."""
    if code and user.mfa_secret is not None:
        step = totp.verify(user.mfa_secret.get_secret_value(), code, now, user.mfa_last_used_step)
        if step is not None:
            user.mfa_last_used_step = step
            return "totp"
        return None
    if recovery_code:
        row = await session.scalar(
            select(MfaRecoveryCode)
            .where(
                MfaRecoveryCode.user_id == user.id,
                MfaRecoveryCode.code_hash == totp.hash_recovery_code(recovery_code),
                MfaRecoveryCode.used_at.is_(None),
            )
            .with_for_update()
        )
        if row is not None:
            row.used_at = now
            return "recovery_code"
    return None


async def verify_mfa(
    session: AsyncSession,
    challenge: str,
    code: str | None,
    recovery_code: str | None,
    client: Client,
    settings: Settings,
    limiter: RateLimiter,
    now: datetime | None = None,
) -> IssuedSession:
    now = now or utcnow()
    await _limit(limiter, "mfa", settings, client)
    try:
        claims = tokens.decode(challenge, tokens.MFA_CHALLENGE, settings)
    except tokens.InvalidTokenError:
        await audit.record_now(
            "auth.mfa.verify",
            AuditOutcome.FAILED,
            actor_ip=client.ip,
            details={"reason": "invalid_challenge"},
        )
        raise AuthenticationFailedError("The sign-in has expired; start again.") from None
    user = await session.scalar(select(User).where(User.id == claims.user_id).with_for_update())
    if user is None or not user.is_active or not user.mfa_enabled or is_locked(user, now):
        reason = "locked" if user is not None and is_locked(user, now) else "not_allowed"
        audit.record(
            session,
            "auth.mfa.verify",
            AuditOutcome.FAILED,
            actor_user_id=claims.user_id,
            actor_ip=client.ip,
            details={"reason": reason},
        )
        await session.commit()
        raise AuthenticationFailedError()
    method = await _check_code(session, user, code, recovery_code, now)
    if method is None:
        audit.record(
            session,
            "auth.mfa.verify",
            AuditOutcome.FAILED,
            actor_user_id=user.id,
            actor_ip=client.ip,
            details={"reason": "wrong_code", "method": "recovery" if recovery_code else "totp"},
        )
        register_failure(session, user, settings, now, client)
        await session.commit()
        raise AuthenticationFailedError("The code is wrong or was already used.")
    issued = _issue(session, user, settings, client, now)
    details: dict[str, Any] = {"mfa": method, "session_id": str(issued.session_id)}
    if method == "recovery_code":
        details["recovery_codes_left"] = await session.scalar(
            select(func.count())
            .select_from(MfaRecoveryCode)
            .where(MfaRecoveryCode.user_id == user.id, MfaRecoveryCode.used_at.is_(None))
        )
    audit.record(
        session,
        "auth.login",
        AuditOutcome.SUCCESS,
        actor_user_id=user.id,
        actor_ip=client.ip,
        details=details,
    )
    await session.commit()
    return issued


# --- refresh and logout ---------------------------------------------------------------------


async def refresh(
    session: AsyncSession,
    refresh_token: str,
    client: Client,
    settings: Settings,
    now: datetime | None = None,
) -> IssuedSession:
    """Rotate the refresh token. A token that was already rotated means it was copied:
    the whole family is revoked and the reuse audited."""
    now = now or utcnow()
    row = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == tokens.hash_refresh_token(refresh_token))
        .with_for_update()
    )
    if row is None:
        raise AuthenticationFailedError("The session has ended; sign in again.")
    if row.revoked_at is not None:
        if row.replaced_by is not None:
            revoked = await revoke_family(session, row.family_id, now)
            audit.record(
                session,
                "auth.refresh.reuse",
                AuditOutcome.FAILED,
                actor_user_id=row.user_id,
                actor_ip=client.ip,
                target_type="session",
                target_id=row.family_id,
                details={"revoked_count": revoked},
            )
            await session.commit()
            logger.warning("refresh token reused", extra={"session_id": str(row.family_id)})
        raise AuthenticationFailedError("The session has ended; sign in again.")
    user = await session.get(User, row.user_id)
    started_at = await session.scalar(
        select(func.min(RefreshToken.created_at)).where(RefreshToken.family_id == row.family_id)
    )
    max_age = timedelta(days=settings.auth_session_max_days)
    if (
        row.expires_at <= now
        or user is None
        or not user.is_active
        or started_at is None
        or started_at + max_age <= now
    ):
        await revoke_family(session, row.family_id, now)
        await session.commit()
        raise AuthenticationFailedError("The session has ended; sign in again.")
    new_row, token = _new_refresh_row(user, row.family_id, started_at, settings, client, now)
    session.add(new_row)
    await session.flush()
    row.revoked_at = now
    row.replaced_by = new_row.id
    access, expires_in = tokens.issue_access_token(user.id, row.family_id, settings, now)
    await session.commit()
    return IssuedSession(
        access,
        expires_in,
        token,
        new_row.expires_at,
        row.family_id,
        requirements_of(user, settings),
    )


async def logout(
    session: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    client: Client,
    now: datetime | None = None,
) -> None:
    now = now or utcnow()
    await revoke_family(session, session_id, now)
    audit.record(
        session,
        "auth.logout",
        AuditOutcome.SUCCESS,
        actor_user_id=user_id,
        actor_ip=client.ip,
        target_type="session",
        target_id=session_id,
    )
    await session.commit()


@dataclass(frozen=True)
class SessionInfo:
    id: uuid.UUID
    started_at: datetime
    last_used_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None


async def active_sessions(
    session: AsyncSession, user_id: uuid.UUID, now: datetime | None = None
) -> list[SessionInfo]:
    """The user's sessions that can still be refreshed, most recently used first."""
    now = now or utcnow()
    first = (
        select(RefreshToken.family_id, func.min(RefreshToken.created_at).label("started_at"))
        .where(RefreshToken.user_id == user_id)
        .group_by(RefreshToken.family_id)
        .subquery()
    )
    rows = await session.execute(
        select(RefreshToken, first.c.started_at)
        .join(first, first.c.family_id == RefreshToken.family_id)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .order_by(RefreshToken.created_at.desc())
    )
    return [
        SessionInfo(
            id=token.family_id,
            started_at=started_at,
            last_used_at=token.created_at,
            expires_at=token.expires_at,
            ip=token.ip,
            user_agent=token.user_agent,
        )
        for token, started_at in rows.all()
    ]


async def revoke_own_session(
    session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID, client: Client
) -> bool:
    now = utcnow()
    owner = await session.scalar(
        select(RefreshToken.user_id).where(RefreshToken.family_id == session_id).limit(1)
    )
    if owner != user_id:
        return False
    await revoke_family(session, session_id, now)
    audit.record(
        session,
        "auth.session.revoke",
        AuditOutcome.SUCCESS,
        actor_user_id=user_id,
        actor_ip=client.ip,
        target_type="session",
        target_id=session_id,
    )
    await session.commit()
    return True


# --- password -------------------------------------------------------------------------------


def check_new_password(user: User, password: str) -> None:
    violations = passwords.check_policy(
        password, username=user.username, names=(user.display_name, user.email)
    )
    if violations:
        raise PasswordRejectedError(violations)


async def change_password(
    session: AsyncSession,
    user: User,
    current: str,
    new: str,
    current_session: uuid.UUID,
    client: Client,
    settings: Settings,
) -> None:
    """The user's own change: needs the current password; ends every other session."""
    now = utcnow()
    if not passwords.verify_password(user.password_hash, current):
        register_failure(session, user, settings, now, client)
        audit.record(
            session,
            "auth.password.change",
            AuditOutcome.FAILED,
            actor_user_id=user.id,
            actor_ip=client.ip,
            target_type="user",
            target_id=user.id,
            details={"reason": "wrong_current_password"},
        )
        await session.commit()
        raise AuthenticationFailedError("The current password is wrong.")
    if passwords.verify_password(user.password_hash, new):
        raise PasswordRejectedError(
            [PolicyViolation("unchanged", "The new password must differ from the current one.")]
        )
    check_new_password(user, new)
    user.password_hash = passwords.hash_password(new)
    user.password_changed_at = now
    user.must_change_password = False
    user.failed_login_count = 0
    revoked = await revoke_user_sessions(session, user.id, now, keep=current_session)
    audit.record(
        session,
        "auth.password.change",
        AuditOutcome.SUCCESS,
        actor_user_id=user.id,
        actor_ip=client.ip,
        target_type="user",
        target_id=user.id,
        details={"other_sessions_ended": revoked},
    )
    await session.commit()


# --- MFA ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Enrollment:
    secret: str
    otpauth_uri: str
    qr_svg: str


async def begin_enrollment(session: AsyncSession, user: User, settings: Settings) -> Enrollment:
    """A new (pending) TOTP secret; MFA is on only after ``confirm_enrollment``."""
    if user.mfa_enabled:
        raise ConflictError("MFA is already enabled; disable it first to enroll a new device.")
    secret = totp.new_secret()
    user.mfa_secret = Secret(secret)
    user.mfa_last_used_step = None
    await session.commit()
    uri = totp.provisioning_uri(secret, user.username, settings.auth_mfa_issuer)
    return Enrollment(secret, uri, totp.qr_svg_data_uri(uri))


async def confirm_enrollment(
    session: AsyncSession, user: User, code: str, client: Client
) -> list[str]:
    """Turn MFA on with a first code from the authenticator; returns the recovery codes,
    which are shown this once."""
    now = utcnow()
    if user.mfa_enabled:
        raise ConflictError("MFA is already enabled.")
    if user.mfa_secret is None:
        raise ConflictError("Start the enrollment first.")
    step = totp.verify(user.mfa_secret.get_secret_value(), code, now, None)
    if step is None:
        audit.record(
            session,
            "auth.mfa.enroll",
            AuditOutcome.FAILED,
            actor_user_id=user.id,
            actor_ip=client.ip,
            target_type="user",
            target_id=user.id,
            details={"reason": "wrong_code"},
        )
        await session.commit()
        raise InvalidCodeError("The code does not match; check the authenticator's clock.")
    user.mfa_enabled = True
    user.mfa_last_used_step = step
    codes = totp.new_recovery_codes()
    await session.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    session.add_all(
        MfaRecoveryCode(user_id=user.id, code_hash=totp.hash_recovery_code(c)) for c in codes
    )
    audit.record(
        session,
        "auth.mfa.enroll",
        AuditOutcome.SUCCESS,
        actor_user_id=user.id,
        actor_ip=client.ip,
        target_type="user",
        target_id=user.id,
    )
    await session.commit()
    return codes


async def clear_mfa(session: AsyncSession, user: User) -> None:
    user.mfa_enabled = False
    user.mfa_secret = None
    user.mfa_last_used_step = None
    await session.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))


async def disable_mfa(
    session: AsyncSession,
    user: User,
    password: str,
    code: str | None,
    recovery_code: str | None,
    client: Client,
    settings: Settings,
) -> None:
    """The user's own: password and a code (TOTP or recovery). Where policy requires MFA,
    the session can then only enroll again."""
    now = utcnow()
    if not user.mfa_enabled:
        raise ConflictError("MFA is not enabled.")
    password_ok = passwords.verify_password(user.password_hash, password)
    method = await _check_code(session, user, code, recovery_code, now) if password_ok else None
    if method is None:
        register_failure(session, user, settings, now, client)
        audit.record(
            session,
            "auth.mfa.disable",
            AuditOutcome.FAILED,
            actor_user_id=user.id,
            actor_ip=client.ip,
            target_type="user",
            target_id=user.id,
            details={"reason": "wrong_password" if not password_ok else "wrong_code"},
        )
        await session.commit()
        raise AuthenticationFailedError("The password or the code is wrong.")
    await clear_mfa(session, user)
    audit.record(
        session,
        "auth.mfa.disable",
        AuditOutcome.SUCCESS,
        actor_user_id=user.id,
        actor_ip=client.ip,
        target_type="user",
        target_id=user.id,
    )
    await session.commit()
