"""Credential profiles (M7). Listing names is ``credentials:read`` (to choose the profiles a
discovery run tries); everything else is ``credentials:manage`` (admins). Secret fields are
write-only: no response carries them, in any form."""

from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from netops.api.problems import VALIDATION_ERROR, ProblemError, problems
from netops.api.schemas.credentials import (
    CredentialProfile,
    CredentialProfileCreate,
    CredentialProfilePage,
    CredentialProfileSummary,
    CredentialProfileUpdate,
)
from netops.api.security import CurrentPrincipal, Principal, guard
from netops.api.v1.common import DEFAULT_LIMIT, Limit, Offset, Session
from netops.auth import credentials
from netops.auth.credentials import InvalidProfileError, ProfileFields
from netops.auth.rbac import Permission
from netops.auth.service import ConflictError
from netops.auth.users import Actor
from netops.core.secrets import Secret
from netops.db import models as m
from netops.db.enums import CredentialKind

router = APIRouter(
    prefix="/credential-profiles",
    tags=["credentials"],
    responses=problems(401, 403, 422),
)
_MANAGE = guard(Permission.CREDENTIALS_MANAGE)


def _secret(value: object) -> Secret | None:
    getter = getattr(value, "get_secret_value", None)
    return Secret(getter()) if getter is not None else None


def _actor(principal: Principal) -> Actor:
    return Actor(user_id=principal.user_id, ip=principal.ip)


async def _detail(session: Session, profile: m.CredentialProfile) -> CredentialProfile:
    await session.refresh(profile)  # updated_at is set by the database
    return CredentialProfile(
        id=profile.id,
        name=profile.name,
        kind=profile.kind,
        username=profile.username,
        enable_secret_set=profile.enable_secret is not None,
        auth_protocol=profile.auth_protocol,
        priv_protocol=profile.priv_protocol,
        devices=await credentials.devices_using(session, profile.id),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


async def _profile(session: Session, profile_id: UUID) -> m.CredentialProfile:
    profile = await session.get(m.CredentialProfile, profile_id)
    if profile is None:
        raise ProblemError(
            HTTPStatus.NOT_FOUND, detail=f"Credential profile {profile_id} does not exist."
        )
    return profile


def _invalid(exc: InvalidProfileError) -> ProblemError:
    return ProblemError(HTTPStatus.UNPROCESSABLE_ENTITY, detail=str(exc), type_=VALIDATION_ERROR)


@router.get("", **guard(Permission.CREDENTIALS_READ))
async def list_credential_profiles(
    session: Session,
    kind: Annotated[list[CredentialKind] | None, Query()] = None,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> CredentialProfilePage:
    """Profiles by name, e.g. to choose the ones a discovery run tries. Only id, name and
    kind."""
    conditions = [m.CredentialProfile.kind.in_(kind)] if kind else []
    total = await session.scalar(
        select(func.count()).select_from(m.CredentialProfile).where(*conditions)
    )
    rows = await session.execute(
        select(m.CredentialProfile.id, m.CredentialProfile.name, m.CredentialProfile.kind)
        .where(*conditions)
        .order_by(m.CredentialProfile.name)
        .limit(limit)
        .offset(offset)
    )
    return CredentialProfilePage(
        items=[
            CredentialProfileSummary(id=pid, name=name, kind=pkind)
            for pid, name, pkind in rows.all()
        ],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.post("", status_code=HTTPStatus.CREATED, responses=problems(409), **_MANAGE)
async def create_credential_profile(
    session: Session, principal: CurrentPrincipal, body: CredentialProfileCreate
) -> CredentialProfile:
    """Create a profile. The secrets are stored encrypted and never returned."""
    fields = ProfileFields(
        name=body.name,
        username=body.username,
        password=_secret(body.password),
        enable_secret=_secret(body.enable_secret),
        auth_protocol=body.auth_protocol,
        auth_key=_secret(body.auth_key),
        priv_protocol=body.priv_protocol,
        priv_key=_secret(body.priv_key),
    )
    try:
        profile = await credentials.create_profile(session, _actor(principal), body.kind, fields)
    except ConflictError as exc:
        raise ProblemError(HTTPStatus.CONFLICT, detail=str(exc)) from None
    except InvalidProfileError as exc:
        raise _invalid(exc) from None
    return await _detail(session, profile)


@router.get("/{profile_id}", responses=problems(404), **_MANAGE)
async def get_credential_profile(session: Session, profile_id: UUID) -> CredentialProfile:
    """A profile without its secrets."""
    return await _detail(session, await _profile(session, profile_id))


@router.patch("/{profile_id}", responses=problems(404, 409), **_MANAGE)
async def update_credential_profile(
    session: Session,
    principal: CurrentPrincipal,
    profile_id: UUID,
    body: CredentialProfileUpdate,
) -> CredentialProfile:
    """Change a profile; a secret is replaced only when it is sent."""
    profile = await _profile(session, profile_id)
    fields = ProfileFields(
        name=body.name,
        username=body.username,
        password=_secret(body.password),
        enable_secret=_secret(body.enable_secret),
        clear_enable_secret=body.clear_enable_secret,
        auth_protocol=body.auth_protocol,
        auth_key=_secret(body.auth_key),
        priv_protocol=body.priv_protocol,
        priv_key=_secret(body.priv_key),
    )
    try:
        await credentials.update_profile(session, _actor(principal), profile, fields)
    except ConflictError as exc:
        raise ProblemError(HTTPStatus.CONFLICT, detail=str(exc)) from None
    except InvalidProfileError as exc:
        raise _invalid(exc) from None
    return await _detail(session, profile)


@router.delete(
    "/{profile_id}",
    status_code=HTTPStatus.NO_CONTENT,
    responses=problems(404, 409),
    **_MANAGE,
)
async def delete_credential_profile(
    session: Session, principal: CurrentPrincipal, profile_id: UUID
) -> None:
    """Delete a profile no device uses (409 otherwise)."""
    profile = await _profile(session, profile_id)
    try:
        await credentials.delete_profile(session, _actor(principal), profile)
    except ConflictError as exc:
        raise ProblemError(HTTPStatus.CONFLICT, detail=str(exc)) from None
