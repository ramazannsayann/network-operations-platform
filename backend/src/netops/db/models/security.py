"""Security (M7): platform users, their MFA recovery codes and sessions, and the audit log.

Device credentials are in ``credentials.py``. Decisions: docs/adr/0008-authentication.md.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Index, func, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from netops.core.secrets import Secret
from netops.db.base import Base
from netops.db.enums import AuditOutcome, UserRole
from netops.db.models._common import EntityMixin, host_address
from netops.db.types import EncryptedSecret

_SHA256_HEX = "~ '^[0-9a-f]{64}$'"


class User(EntityMixin, Base):
    """A person who signs in to the platform. Deactivated, never deleted (the audit log
    keeps referring to them)."""

    __tablename__ = "users"
    __table_args__ = (
        # Stored lower-case, so the plain unique constraint is case-insensitive.
        CheckConstraint(
            "username ~ '^[a-z0-9][a-z0-9._@-]{2,63}$'", name="username_lower_case_format"
        ),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_non_negative"),
        CheckConstraint(
            "NOT mfa_enabled OR mfa_secret_encrypted IS NOT NULL", name="mfa_enabled_has_secret"
        ),
    )

    username: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str]
    email: Mapped[str | None]
    # argon2id, PHC string format ($argon2id$v=19$m=...,t=...,p=...$salt$hash).
    password_hash: Mapped[str]
    role: Mapped[UserRole]
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    # Set by an admin (new user, password reset): the next session may only change it.
    must_change_password: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    mfa_enabled: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    # TOTP secret, Fernet-encrypted with CREDENTIALS_KEY; set (pending) during enrollment.
    mfa_secret: Mapped[Secret | None] = mapped_column("mfa_secret_encrypted", EncryptedSecret)
    # Last accepted TOTP time step: a code cannot be used twice.
    mfa_last_used_step: Mapped[int | None] = mapped_column(BigInteger)
    failed_login_count: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[datetime | None]
    password_changed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_login_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class MfaRecoveryCode(EntityMixin, Base):
    """One single-use recovery code (10 per enrollment), stored as a sha256 hash."""

    __tablename__ = "mfa_recovery_codes"
    __table_args__ = (CheckConstraint(f"code_hash {_SHA256_HEX}", name="code_hash_format"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    used_at: Mapped[datetime | None]


# The unused codes of a user, checked at MFA verification.
Index("ix_mfa_recovery_codes_user_id", MfaRecoveryCode.user_id)


class RefreshToken(EntityMixin, Base):
    """A refresh token, stored as a sha256 hash. Each use rotates it: the old row is revoked
    and points at its replacement. All tokens descending from one login form a family (a
    session); presenting a revoked token again revokes the whole family."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint(f"token_hash {_SHA256_HEX}", name="token_hash_format"),
        CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        host_address("ip"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    family_id: Mapped[uuid.UUID]
    token_hash: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None]


# Revoking a family, and checking on every request that the session is still active.
Index("ix_refresh_tokens_family_id", RefreshToken.family_id)
# A user's sessions, newest first.
Index("ix_refresh_tokens_user_id_created_at", RefreshToken.user_id, RefreshToken.created_at)


class AuditLogEntry(Base):
    """Append-only: a database trigger rejects UPDATE, DELETE and TRUNCATE.

    ``actor_user_id`` has no foreign key on purpose: entries must never change, not even
    by ON DELETE SET NULL. ``details`` never holds secrets.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint("action ~ '^[a-z]+(\\.[a-z_]+)+$'", name="action_format"),
        host_address("actor_ip"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    at: Mapped[datetime] = mapped_column(server_default=func.now())
    actor_user_id: Mapped[uuid.UUID | None]
    actor_ip: Mapped[str | None] = mapped_column(INET)
    action: Mapped[str]
    target_type: Mapped[str | None]
    target_id: Mapped[str | None]
    outcome: Mapped[AuditOutcome]
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


# The audit page: newest first, by actor, by action.
Index("ix_audit_log_at", AuditLogEntry.at.desc())
Index("ix_audit_log_actor_user_id_at", AuditLogEntry.actor_user_id, AuditLogEntry.at.desc())
Index("ix_audit_log_action_at", AuditLogEntry.action, AuditLogEntry.at.desc())
