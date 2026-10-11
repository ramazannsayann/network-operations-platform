"""Configuration management (M4): backups, versions, redacted texts and diffs, changes.

Texts come from the configuration repository (netops.configmgmt.store, a read-only mount
in the api container) and are redacted before they are returned (ADR-0007).
"""

import asyncio
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from netops.api.problems import ProblemError, problems
from netops.api.schemas.common import DeviceRef
from netops.api.schemas.configs import (
    ConfigBackupSummary,
    ConfigBackupSummaryPage,
    ConfigChange,
    ConfigChangePage,
    ConfigDiff,
    ConfigVersion,
    ConfigVersionContent,
    ConfigVersionPage,
)
from netops.api.security import guard
from netops.api.v1.common import DEFAULT_LIMIT, From, Limit, Offset, SearchText, Session, To
from netops.auth.rbac import Permission
from netops.configmgmt.diff import redacted_diff
from netops.configmgmt.redact import redact, redact_commands
from netops.configmgmt.store import ConfigStore, ConfigStoreError
from netops.core.settings import get_settings
from netops.db import models as m
from netops.db.enums import ChangeOrigin, CollectionKind, CollectionStatus

router = APIRouter(tags=["configs"], responses=problems(401, 403, 422, 501))

VersionSort = Literal["collected_at", "-collected_at"]
ChangeSort = Literal["detected_at", "-detected_at"]
BackupSort = Literal["hostname", "-hostname", "last_change_at", "-last_change_at"]


def _ip(address: str | None) -> IPv4Address | IPv6Address | None:
    return ip_address(address) if address else None


def _device_ref(device: m.Device) -> DeviceRef:
    return DeviceRef(id=device.id, hostname=device.hostname, mgmt_ip=_ip(device.mgmt_ip))


def _version(row: m.ConfigVersion) -> ConfigVersion:
    return ConfigVersion.model_validate(row, from_attributes=True)


async def _device(session: AsyncSession, device_id: UUID) -> m.Device:
    device = await session.get(m.Device, device_id)
    if device is None:
        raise ProblemError(status.HTTP_404_NOT_FOUND, detail=f"Device {device_id} does not exist.")
    return device


async def _version_row(session: AsyncSession, version_id: UUID) -> m.ConfigVersion:
    version = await session.get(m.ConfigVersion, version_id)
    if version is None:
        raise ProblemError(
            status.HTTP_404_NOT_FOUND, detail=f"Configuration version {version_id} does not exist."
        )
    return version


async def _text(version: m.ConfigVersion) -> str:
    """The complete text from Git: only ever passed on redacted."""
    store = ConfigStore(get_settings().config_repo_path)
    try:
        return await asyncio.to_thread(store.read, version.git_commit, version.device_id)
    except ConfigStoreError:
        raise ProblemError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The configuration repository has no text for version {version.id}.",
        ) from None


def _range(column: Any, from_: datetime | None, to: datetime | None) -> list[ColumnElement[bool]]:
    conditions = []
    if from_ is not None:
        conditions.append(column >= from_)
    if to is not None:
        conditions.append(column < to)
    return conditions


@router.get("/config-backups", **guard(Permission.CONFIGS_READ))
async def list_config_backups(
    session: Session,
    q: SearchText = None,
    days: Annotated[
        int, Query(ge=1, le=90, description="Window for ``recent_external_changes``.")
    ] = 7,
    sort: BackupSort = "hostname",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> ConfigBackupSummaryPage:
    """Backup state of every managed device: last backup, versions, recent external changes."""
    conditions: list[ColumnElement[bool]] = [m.Device.is_managed.is_(True)]
    if q:
        pattern = f"%{q}%"
        conditions.append(
            m.Device.hostname.ilike(pattern) | func.host(m.Device.mgmt_ip).ilike(pattern)
        )
    total = await session.scalar(select(func.count()).select_from(m.Device).where(*conditions))
    since = datetime.now(UTC) - timedelta(days=days)
    changes = (
        select(
            m.ConfigChange.device_id,
            func.max(m.ConfigChange.detected_at).label("last_change_at"),
            func.count()
            .filter(
                m.ConfigChange.origin == ChangeOrigin.EXTERNAL,
                m.ConfigChange.detected_at >= since,
            )
            .label("recent"),
        )
        .group_by(m.ConfigChange.device_id)
        .subquery()
    )
    stmt = (
        select(m.Device, changes.c.last_change_at, changes.c.recent)
        .outerjoin(changes, changes.c.device_id == m.Device.id)
        .where(*conditions)
    )
    descending = sort.startswith("-")
    column: Any = (
        changes.c.last_change_at if sort.lstrip("-") == "last_change_at" else m.Device.hostname
    )
    stmt = stmt.order_by(
        column.desc().nulls_last() if descending else column.asc().nulls_last(), m.Device.mgmt_ip
    )
    rows = (await session.execute(stmt.limit(limit).offset(offset))).all()
    ids = [device.id for device, _, _ in rows]

    counts: dict[UUID, int] = dict(
        (
            await session.execute(
                select(m.ConfigVersion.device_id, func.count())
                .where(m.ConfigVersion.device_id.in_(ids))
                .group_by(m.ConfigVersion.device_id)
            )
        ).all()
    )
    latest = {
        v.device_id: v
        for v in await session.scalars(
            select(m.ConfigVersion)
            .ext(distinct_on(m.ConfigVersion.device_id))
            .where(m.ConfigVersion.device_id.in_(ids))
            .order_by(m.ConfigVersion.device_id, m.ConfigVersion.collected_at.desc())
        )
    }
    config_runs = select(m.CollectionRun).where(
        m.CollectionRun.device_id.in_(ids),
        m.CollectionRun.kind == CollectionKind.CONFIG,
        m.CollectionRun.status != CollectionStatus.RUNNING,
    )
    last_attempt = {
        r.device_id: r
        for r in await session.scalars(
            config_runs.ext(distinct_on(m.CollectionRun.device_id)).order_by(
                m.CollectionRun.device_id, m.CollectionRun.started_at.desc()
            )
        )
    }
    last_success = {
        r.device_id: r
        for r in await session.scalars(
            config_runs.where(m.CollectionRun.status == CollectionStatus.SUCCESS)
            .ext(distinct_on(m.CollectionRun.device_id))
            .order_by(m.CollectionRun.device_id, m.CollectionRun.started_at.desc())
        )
    }
    items = []
    for device, last_change_at, recent in rows:
        attempt, success = last_attempt.get(device.id), last_success.get(device.id)
        version = latest.get(device.id)
        items.append(
            ConfigBackupSummary(
                device=_device_ref(device),
                last_backup_at=success.finished_at if success else None,
                last_backup_status=attempt.status if attempt else None,
                version_count=counts.get(device.id, 0),
                latest_version=_version(version) if version else None,
                last_change_at=last_change_at,
                recent_external_changes=recent or 0,
            )
        )
    return ConfigBackupSummaryPage(items=items, total=total or 0, limit=limit, offset=offset)


@router.get(
    "/devices/{device_id}/configs", responses=problems(404), **guard(Permission.CONFIGS_READ)
)
async def list_device_configs(
    session: Session,
    device_id: UUID,
    from_: From = None,
    to: To = None,
    sort: VersionSort = "-collected_at",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> ConfigVersionPage:
    """Configuration versions of a device; ``from``/``to`` filter on ``collected_at``."""
    await _device(session, device_id)
    conditions = [
        m.ConfigVersion.device_id == device_id,
        *_range(m.ConfigVersion.collected_at, from_, to),
    ]
    total = await session.scalar(
        select(func.count()).select_from(m.ConfigVersion).where(*conditions)
    )
    order = (
        m.ConfigVersion.collected_at.desc()
        if sort.startswith("-")
        else m.ConfigVersion.collected_at.asc()
    )
    rows = await session.scalars(
        select(m.ConfigVersion).where(*conditions).order_by(order).limit(limit).offset(offset)
    )
    return ConfigVersionPage(
        items=[_version(v) for v in rows], total=total or 0, limit=limit, offset=offset
    )


def _label(device: m.Device, version: m.ConfigVersion) -> str:
    when = version.collected_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{device.hostname or device.mgmt_ip} @ {when}"


# Declared before /configs/{version_id} so "diff" is not taken for a version id.
@router.get("/configs/diff", responses=problems(404, 503), **guard(Permission.CONFIGS_READ))
async def diff_configs(
    session: Session,
    from_: Annotated[UUID, Query(alias="from", description="Older version id.")],
    to: Annotated[UUID, Query(description="Newer version id (may be of another device).")],
    context_lines: Annotated[int, Query(ge=0, le=50)] = 3,
) -> ConfigDiff:
    """Unified diff between two configuration versions, redacted (a changed secret still
    shows as a changed line)."""
    old, new = await _version_row(session, from_), await _version_row(session, to)
    old_device = await _device(session, old.device_id)
    new_device = await _device(session, new.device_id)
    old_text, new_text = await _text(old), await _text(new)
    diff = redacted_diff(
        old_text,
        new_text,
        from_label=_label(old_device, old),
        to_label=_label(new_device, new),
        context=context_lines,
    )
    return ConfigDiff(
        from_version=_version(old),
        to_version=_version(new),
        unified_diff=diff.text,
        added_lines=diff.added,
        removed_lines=diff.removed,
    )


@router.get("/configs/{version_id}", responses=problems(404, 503), **guard(Permission.CONFIGS_READ))
async def get_config_version(session: Session, version_id: UUID) -> ConfigVersionContent:
    """A configuration version with its normalized text, secrets redacted."""
    version = await _version_row(session, version_id)
    content = redact(await _text(version))
    return ConfigVersionContent.model_validate(
        _version(version).model_dump() | {"content": content}
    )


@router.get("/config-changes", **guard(Permission.CONFIGS_READ))
async def list_config_changes(
    session: Session,
    device_id: UUID | None = None,
    origin: Annotated[list[ChangeOrigin] | None, Query()] = None,
    username: Annotated[
        str | None, Query(min_length=1, max_length=200, description="Exact user name.")
    ] = None,
    from_: From = None,
    to: To = None,
    sort: ChangeSort = "-detected_at",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> ConfigChangePage:
    """Detected configuration changes; ``from``/``to`` filter on ``detected_at``."""
    conditions: list[ColumnElement[bool]] = _range(m.ConfigChange.detected_at, from_, to)
    if device_id is not None:
        conditions.append(m.ConfigChange.device_id == device_id)
    if origin:
        conditions.append(m.ConfigChange.origin.in_(origin))
    if username is not None:
        conditions.append(m.ConfigChange.username == username)
    total = await session.scalar(
        select(func.count()).select_from(m.ConfigChange).where(*conditions)
    )
    order = (
        m.ConfigChange.detected_at.desc()
        if sort.startswith("-")
        else m.ConfigChange.detected_at.asc()
    )
    after = m.ConfigVersion
    rows = (
        await session.execute(
            select(m.ConfigChange, m.Device, after.trigger)
            .join(m.Device, m.Device.id == m.ConfigChange.device_id)
            .outerjoin(after, and_(after.id == m.ConfigChange.after_version_id))
            .where(*conditions)
            .order_by(order, m.ConfigChange.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [
        ConfigChange(
            id=change.id,
            device=_device_ref(device),
            detected_at=change.detected_at,
            origin=change.origin,
            username=change.username,
            source_ip=_ip(change.source_ip),
            commands=redact_commands(change.commands),  # stored redacted; again for safety
            before_version_id=change.before_version_id,
            after_version_id=change.after_version_id,
            detected_by=trigger,
        )
        for change, device, trigger in rows
    ]
    return ConfigChangePage(items=items, total=total or 0, limit=limit, offset=offset)
