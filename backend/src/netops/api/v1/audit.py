"""The audit log (M7): admins only (``audit:read``). Read-only: there is no way to change
or delete entries, here or in the database."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, func, or_, select

from netops.api.problems import problems
from netops.api.schemas.audit import AuditActor, AuditEntry, AuditPage
from netops.api.security import guard
from netops.api.v1.common import DEFAULT_LIMIT, From, Limit, Offset, Session, To
from netops.auth.rbac import Permission
from netops.db import models as m
from netops.db.enums import AuditOutcome

router = APIRouter(prefix="/audit", tags=["audit"], responses=problems(401, 403, 422))

AuditSort = Literal["at", "-at"]


@router.get("", **guard(Permission.AUDIT_READ))
async def list_audit_entries(
    session: Session,
    actor_user_id: UUID | None = None,
    actor: Annotated[
        str | None, Query(min_length=1, max_length=200, description="Actor's username.")
    ] = None,
    action: Annotated[
        list[str] | None,
        Query(description='e.g. "auth.login"; a trailing ".*" matches a prefix ("auth.*").'),
    ] = None,
    target_type: str | None = None,
    target_id: str | None = None,
    outcome: Annotated[list[AuditOutcome] | None, Query()] = None,
    from_: From = None,
    to: To = None,
    sort: AuditSort = "-at",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> AuditPage:
    """Audit entries, newest first; ``from``/``to`` filter on ``at``."""
    entry = m.AuditLogEntry
    conditions: list[ColumnElement[bool]] = []
    if actor_user_id is not None:
        conditions.append(entry.actor_user_id == actor_user_id)
    if actor:
        ids = select(m.User.id).where(m.User.username == actor.strip().lower())
        conditions.append(entry.actor_user_id.in_(ids))
    if action:
        matches = [
            entry.action.startswith(a[:-1]) if a.endswith(".*") else entry.action == a
            for a in action
        ]
        conditions.append(or_(*matches))
    if target_type:
        conditions.append(entry.target_type == target_type)
    if target_id:
        conditions.append(entry.target_id == target_id)
    if outcome:
        conditions.append(entry.outcome.in_(outcome))
    if from_ is not None:
        conditions.append(entry.at >= from_)
    if to is not None:
        conditions.append(entry.at < to)
    total = await session.scalar(select(func.count()).select_from(entry).where(*conditions))
    order = (entry.at.desc(), entry.id.desc()) if sort == "-at" else (entry.at, entry.id)
    rows = await session.execute(
        select(entry, m.User.username)
        .outerjoin(m.User, m.User.id == entry.actor_user_id)
        .where(*conditions)
        .order_by(*order)
        .limit(limit)
        .offset(offset)
    )
    items = [
        AuditEntry(
            id=row.id,
            at=row.at,
            actor=AuditActor(id=row.actor_user_id, username=username)
            if row.actor_user_id
            else None,
            actor_ip=row.actor_ip,  # type: ignore[arg-type]  # pydantic parses the string
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            outcome=row.outcome,
            details=row.details,
        )
        for row, username in rows.all()
    ]
    return AuditPage(items=items, total=total or 0, limit=limit, offset=offset)
