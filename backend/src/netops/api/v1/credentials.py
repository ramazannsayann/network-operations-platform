"""Credential profiles (minimal M7): listing for selection; secrets are never returned."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from netops.api.problems import problems
from netops.api.schemas.credentials import CredentialProfilePage, CredentialProfileSummary
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import DEFAULT_LIMIT, Limit, Offset, Session
from netops.db import models as m
from netops.db.enums import CredentialKind

router = APIRouter(
    prefix="/credential-profiles",
    tags=["credentials"],
    dependencies=AUTHENTICATED,
    responses=problems(401, 422),
)


@router.get("")
async def list_credential_profiles(
    session: Session,
    kind: Annotated[list[CredentialKind] | None, Query()] = None,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> CredentialProfilePage:
    """Profiles by name, e.g. to choose the ones a discovery run tries. Only id, name and
    kind: usernames and secrets stay in the database (add profiles with ``netops
    credentials add``)."""
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
