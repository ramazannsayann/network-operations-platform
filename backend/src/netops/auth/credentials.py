"""Credential profile administration (API and CLI), audited by name only.

Secrets arrive as ``Secret`` objects and leave only as Fernet tokens in the database
(ADR-0004); nothing here returns them. A profile some device uses cannot be deleted.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from netops.auth import audit
from netops.auth.service import ConflictError
from netops.auth.users import Actor
from netops.core.secrets import Secret
from netops.db.enums import AuditOutcome, CredentialKind, SnmpAuthProtocol, SnmpPrivProtocol
from netops.db.models import CredentialProfile, Device


class InvalidProfileError(ValueError):
    """The fields do not make a valid profile of its kind."""


@dataclass
class ProfileFields:
    """What to set; ``None`` leaves a field unchanged on update."""

    name: str | None = None
    username: str | None = None
    password: Secret | None = None
    enable_secret: Secret | None = None
    clear_enable_secret: bool = False
    auth_protocol: SnmpAuthProtocol | None = None
    auth_key: Secret | None = None
    priv_protocol: SnmpPrivProtocol | None = None
    priv_key: Secret | None = None
    changed: list[str] = field(default_factory=list)


def _validate(profile: CredentialProfile) -> None:
    if not profile.name or not profile.username:
        raise InvalidProfileError("name and username are required")
    if profile.kind is CredentialKind.SSH:
        if profile.password is None:
            raise InvalidProfileError("an SSH profile needs a password")
        if profile.auth_protocol or profile.auth_key or profile.priv_protocol or profile.priv_key:
            raise InvalidProfileError("SNMPv3 fields do not belong to an SSH profile")
    else:
        if not (profile.auth_protocol and profile.auth_key and profile.priv_protocol):
            raise InvalidProfileError(
                "an SNMPv3 profile needs auth_protocol, auth_key, priv_protocol and priv_key"
            )
        if profile.priv_key is None:
            raise InvalidProfileError("an SNMPv3 profile needs priv_key")
        if profile.password is not None or profile.enable_secret is not None:
            raise InvalidProfileError("password and enable_secret belong to SSH profiles")


def _apply(profile: CredentialProfile, fields: ProfileFields) -> list[str]:
    """Set the given fields; the names of what changed (secrets by name only)."""
    changed = []
    for attribute in ("name", "username", "auth_protocol", "priv_protocol"):
        value = getattr(fields, attribute)
        if value is not None and value != getattr(profile, attribute):
            setattr(profile, attribute, value)
            changed.append(attribute)
    for attribute in ("password", "enable_secret", "auth_key", "priv_key"):
        value = getattr(fields, attribute)
        if value is not None:
            setattr(profile, attribute, value)
            changed.append(attribute)
    if fields.clear_enable_secret and profile.enable_secret is not None:
        profile.enable_secret = None
        changed.append("enable_secret")
    return changed


async def _name_taken(session: AsyncSession, name: str, other_than: uuid.UUID | None) -> bool:
    conditions = [CredentialProfile.name == name]
    if other_than is not None:
        conditions.append(CredentialProfile.id != other_than)
    return await session.scalar(select(CredentialProfile.id).where(*conditions)) is not None


async def create_profile(
    session: AsyncSession, actor: Actor, kind: CredentialKind, fields: ProfileFields
) -> CredentialProfile:
    if fields.name and await _name_taken(session, fields.name, None):
        raise ConflictError(f"A credential profile named {fields.name!r} already exists.")
    profile = CredentialProfile(id=uuid.uuid4(), kind=kind)
    _apply(profile, fields)
    _validate(profile)
    session.add(profile)
    audit.record(
        session,
        "credentials.create",
        AuditOutcome.SUCCESS,
        actor_user_id=actor.user_id,
        actor_ip=actor.ip,
        target_type="credential_profile",
        target_id=profile.id,
        details={"profile_name": profile.name, "profile_kind": kind.value},
    )
    await session.commit()
    return profile


async def update_profile(
    session: AsyncSession, actor: Actor, profile: CredentialProfile, fields: ProfileFields
) -> CredentialProfile:
    if fields.name and await _name_taken(session, fields.name, profile.id):
        raise ConflictError(f"A credential profile named {fields.name!r} already exists.")
    changed = _apply(profile, fields)
    _validate(profile)
    if changed:
        audit.record(
            session,
            "credentials.update",
            AuditOutcome.SUCCESS,
            actor_user_id=actor.user_id,
            actor_ip=actor.ip,
            target_type="credential_profile",
            target_id=profile.id,
            details={"profile_name": profile.name, "fields": changed},
        )
    await session.commit()
    return profile


async def devices_using(session: AsyncSession, profile_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count()).select_from(Device).where(Device.credential_profile_id == profile_id)
    )
    return int(count or 0)


async def delete_profile(session: AsyncSession, actor: Actor, profile: CredentialProfile) -> None:
    used = await devices_using(session, profile.id)
    if used:
        raise ConflictError(f"{used} devices use this profile; move them to another one first.")
    await session.delete(profile)
    audit.record(
        session,
        "credentials.delete",
        AuditOutcome.SUCCESS,
        actor_user_id=actor.user_id,
        actor_ip=actor.ip,
        target_type="credential_profile",
        target_id=profile.id,
        details={"profile_name": profile.name, "profile_kind": profile.kind.value},
    )
    await session.commit()
