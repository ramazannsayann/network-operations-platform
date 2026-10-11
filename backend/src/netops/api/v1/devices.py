"""Devices and interfaces (M1/M2)."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from netops.api.problems import ProblemError, not_implemented, problems
from netops.api.schemas.common import JobRef, LocationRef
from netops.api.schemas.devices import (
    CollectionFreshness,
    Device,
    DevicePage,
    DeviceRefreshRequest,
    DeviceSerial,
    DeviceSummary,
    InterfaceDetail,
    InterfacePage,
    InterfaceState,
    InterfaceSummary,
)
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import (
    ACCEPTED,
    DEFAULT_LIMIT,
    At,
    Enqueue,
    Limit,
    Offset,
    SearchText,
    Session,
)
from netops.db import models as m
from netops.db.enums import (
    AlarmState,
    CollectionKind,
    CollectionStatus,
    CollectionTrigger,
    DeviceRole,
    DeviceType,
    InterfaceKind,
    JobKind,
    ManagementStatus,
    Reachability,
)
from netops.db.state import observations_of, run_at
from netops.workers.jobs import new_job

router = APIRouter(tags=["devices"], dependencies=AUTHENTICATED, responses=problems(401, 422, 501))

DeviceSort = Literal[
    "hostname", "-hostname", "mgmt_ip", "-mgmt_ip", "last_seen_at", "-last_seen_at"
]
InterfaceSort = Literal["name_normalized", "-name_normalized"]

_DEVICE_ORDER = {
    "hostname": m.Device.hostname,
    "mgmt_ip": m.Device.mgmt_ip,
    "last_seen_at": m.Device.last_seen_at,
}


def _ordered[T: Any](stmt: Select[T], column: Any, descending: bool, tiebreak: Any) -> Select[T]:
    first = column.desc().nulls_last() if descending else column.asc().nulls_last()
    return stmt.order_by(first, tiebreak)


async def _location_refs(session: AsyncSession) -> dict[UUID, LocationRef]:
    """Every location with its full path (the table is small and hierarchical)."""
    locations = {loc.id: loc for loc in await session.scalars(select(m.Location))}

    def path(location_id: UUID) -> str:
        names, seen, current = [], set(), locations.get(location_id)
        while current is not None and current.id not in seen:
            seen.add(current.id)
            names.append(current.name)
            current = locations.get(current.parent_id) if current.parent_id else None
        return " / ".join(reversed(names))

    return {i: LocationRef(id=i, name=loc.name, path=path(i)) for i, loc in locations.items()}


async def _summaries(session: AsyncSession, devices: Sequence[m.Device]) -> list[DeviceSummary]:
    ids = [d.id for d in devices]
    serials: dict[UUID, list[m.DeviceSerial]] = {}
    for serial in await session.scalars(
        select(m.DeviceSerial)
        .where(m.DeviceSerial.device_id.in_(ids))
        .order_by(m.DeviceSerial.stack_member.nulls_first(), m.DeviceSerial.serial)
    ):
        serials.setdefault(serial.device_id, []).append(serial)
    alarm_counts = await session.execute(
        select(m.Alarm.device_id, func.count())
        .where(m.Alarm.device_id.in_(ids), m.Alarm.state != AlarmState.CLEARED)
        .group_by(m.Alarm.device_id)
    )
    alarms: dict[UUID, int] = dict(alarm_counts.all())
    locations = await _location_refs(session) if any(d.location_id for d in devices) else {}
    return [
        DeviceSummary.model_validate(
            {
                **{c: getattr(d, c) for c in _SUMMARY_COLUMNS},
                "location": locations.get(d.location_id) if d.location_id else None,
                "serials": [s.serial for s in serials.get(d.id, [])],
                "open_alarm_count": alarms.get(d.id, 0),
            }
        )
        for d in devices
    ]


_SUMMARY_COLUMNS = (
    "id",
    "hostname",
    "mgmt_ip",
    "device_type",
    "role",
    "vendor",
    "model",
    "os_family",
    "os_version",
    "is_managed",
    "management_status",
    "reachability",
    "discovered_via",
    "first_seen_at",
    "last_seen_at",
    "last_polled_at",
)


@router.get("/devices")
async def list_devices(
    session: Session,
    device_type: Annotated[list[DeviceType] | None, Query()] = None,
    role: Annotated[list[DeviceRole] | None, Query()] = None,
    location_id: UUID | None = None,
    reachability: Annotated[list[Reachability] | None, Query()] = None,
    management_status: Annotated[list[ManagementStatus] | None, Query()] = None,
    q: SearchText = None,
    sort: DeviceSort = "hostname",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> DevicePage:
    """Inventory. ``q`` matches hostname, management IP or serial number (substring).

    Devices discovery found but does not manage (out of scope, wrong credentials, access
    points...) are included; ``management_status`` tells them apart.
    """
    conditions: list[ColumnElement[bool]] = []
    if device_type:
        conditions.append(m.Device.device_type.in_(device_type))
    if role:
        conditions.append(m.Device.role.in_(role))
    if location_id:
        conditions.append(m.Device.location_id == location_id)
    if reachability:
        conditions.append(m.Device.reachability.in_(reachability))
    if management_status:
        conditions.append(m.Device.management_status.in_(management_status))
    if q:
        pattern = f"%{q}%"
        serial_match = select(m.DeviceSerial.device_id).where(m.DeviceSerial.serial.ilike(pattern))
        conditions.append(
            or_(
                m.Device.hostname.ilike(pattern),
                func.host(m.Device.mgmt_ip).ilike(pattern),
                m.Device.id.in_(serial_match),
            )
        )
    total = await session.scalar(select(func.count()).select_from(m.Device).where(*conditions))
    stmt = select(m.Device).where(*conditions)
    stmt = _ordered(stmt, _DEVICE_ORDER[sort.lstrip("-")], sort.startswith("-"), m.Device.id)
    devices = list(await session.scalars(stmt.limit(limit).offset(offset)))
    return DevicePage(
        items=await _summaries(session, devices), total=total or 0, limit=limit, offset=offset
    )


async def _device(session: AsyncSession, device_id: UUID) -> m.Device:
    device = await session.get(m.Device, device_id)
    if device is None:
        raise ProblemError(status.HTTP_404_NOT_FOUND, detail=f"Device {device_id} does not exist.")
    return device


@router.get("/devices/{device_id}", responses=problems(404))
async def get_device(session: Session, device_id: UUID) -> Device:
    device = await _device(session, device_id)
    (summary,) = await _summaries(session, [device])
    serials = await session.scalars(
        select(m.DeviceSerial)
        .where(m.DeviceSerial.device_id == device_id)
        .order_by(m.DeviceSerial.stack_member.nulls_first(), m.DeviceSerial.serial)
    )
    interface_count = await session.scalar(
        select(func.count()).select_from(m.Interface).where(m.Interface.device_id == device_id)
    )
    return Device.model_validate(
        {
            **summary.model_dump(),
            "serial_details": [DeviceSerial.model_validate(s) for s in serials],
            "sys_object_id": device.sys_object_id,
            "interface_count": interface_count or 0,
            "collections": await _freshness(session, device_id),
        }
    )


async def _freshness(session: AsyncSession, device_id: UUID) -> list[CollectionFreshness]:
    """Latest run per kind, and when the kind last succeeded."""
    latest = (
        select(m.CollectionRun)
        .where(m.CollectionRun.device_id == device_id)
        .ext(distinct_on(m.CollectionRun.kind))
        .order_by(m.CollectionRun.kind, m.CollectionRun.started_at.desc())
    )
    successes = await session.execute(
        select(m.CollectionRun.kind, func.max(m.CollectionRun.started_at))
        .where(
            m.CollectionRun.device_id == device_id,
            m.CollectionRun.status.in_([CollectionStatus.SUCCESS, CollectionStatus.PARTIAL]),
        )
        .group_by(m.CollectionRun.kind)
    )
    success: dict[CollectionKind, datetime] = dict(successes.all())
    return [
        CollectionFreshness(
            kind=run.kind,
            last_status=run.status,
            last_started_at=run.started_at,
            last_success_at=success.get(run.kind),
        )
        for run in await session.scalars(latest)
    ]


@router.post(
    "/devices/{device_id}/refresh",
    status_code=status.HTTP_202_ACCEPTED,
    responses=ACCEPTED | problems(404, 409),
)
async def refresh_device(
    session: Session,
    enqueue: Enqueue,
    response: Response,
    device_id: UUID,
    body: DeviceRefreshRequest | None = None,
) -> JobRef:
    """Collect the device's state now ("refresh now"). 409 if it is not managed."""
    device = await _device(session, device_id)
    if not device.is_managed:
        raise ProblemError(
            status.HTTP_409_CONFLICT,
            detail=f"Device {device_id} is not managed ({device.management_status.value}).",
        )
    job = new_job(JobKind.DEVICE_REFRESH, device_id)
    session.add(job)
    await session.commit()
    kinds = [k.value for k in body.kinds] if body and body.kinds else None
    enqueue(
        "netops.collect_device", str(device_id), kinds, CollectionTrigger.MANUAL.value, str(job.id)
    )
    href = f"/api/v1/jobs/{job.id}"
    response.headers["Location"] = href
    return JobRef(
        id=job.id,
        kind=job.kind,
        status=job.status,
        href=href,
        target_href=f"/api/v1/devices/{device_id}",
    )


@router.get("/devices/{device_id}/interfaces", responses=problems(404))
async def list_device_interfaces(
    session: Session,
    device_id: UUID,
    at: At = None,
    kind: Annotated[list[InterfaceKind] | None, Query()] = None,
    oper_up: bool | None = None,
    sort: InterfaceSort = "name_normalized",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> InterfacePage:
    """Interfaces of a device with their state at ``at`` (default: latest)."""
    await _device(session, device_id)
    run = await run_at(session, device_id, CollectionKind.INTERFACES, at, include_partial=True)
    states: dict[uuid.UUID, InterfaceState] = {}
    if run is not None:
        for snapshot in await session.scalars(observations_of(m.InterfaceSnapshot, run)):
            states[snapshot.interface_id] = InterfaceState.model_validate(
                {
                    **{c: getattr(snapshot, c) for c in _STATE_COLUMNS},
                    "observed_at": snapshot.collected_at,
                    "run_id": snapshot.run_id,
                }
            )

    conditions: list[ColumnElement[bool]] = [m.Interface.device_id == device_id]
    if at is not None:
        conditions.append(m.Interface.first_seen_at <= at)
    if kind:
        conditions.append(m.Interface.kind.in_(kind))
    interfaces = list(await session.scalars(select(m.Interface).where(*conditions)))
    if oper_up is not None:
        interfaces = [i for i in interfaces if i.id in states and states[i.id].oper_up is oper_up]
    interfaces.sort(key=lambda i: i.name_normalized, reverse=sort.startswith("-"))
    page = interfaces[offset : offset + limit]
    return InterfacePage(
        items=[
            InterfaceSummary.model_validate(
                {
                    "id": i.id,
                    "device_id": i.device_id,
                    "name": i.name,
                    "name_normalized": i.name_normalized,
                    "kind": i.kind,
                    "description": i.description,
                    "mac": i.mac,
                    "parent_interface_id": i.parent_interface_id,
                    "state": states.get(i.id),
                }
            )
            for i in page
        ],
        total=len(interfaces),
        limit=limit,
        offset=offset,
    )


_STATE_COLUMNS = (
    "admin_up",
    "oper_up",
    "speed_mbps",
    "duplex",
    "mtu",
    "switchport_mode",
    "access_vlan",
    "native_vlan",
    "allowed_vlans",
    "err_disabled_reason",
    "in_errors",
    "crc_errors",
    "late_collisions",
)


@router.get("/interfaces/{interface_id}", responses=problems(404))
async def get_interface(interface_id: UUID, at: At = None) -> InterfaceDetail:
    """One interface: addresses, link peer, port-channel members and its state at ``at``."""
    raise not_implemented()
