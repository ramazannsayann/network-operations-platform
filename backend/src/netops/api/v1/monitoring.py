"""Metrics and syslog/trap events (M3)."""

from ipaddress import ip_address
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import Field
from sqlalchemy import ColumnElement, func, select

from netops.api.problems import not_implemented, problems
from netops.api.schemas.common import DeviceRef
from netops.api.schemas.monitoring import Aggregation, Event, EventPage, MetricSeriesSet
from netops.api.security import guard
from netops.api.v1.common import DEFAULT_LIMIT, From, Limit, Offset, Session, To
from netops.auth.rbac import Permission
from netops.db import models as m
from netops.db.enums import EventKind

router = APIRouter(responses=problems(401, 403, 422, 501))

EventSort = Literal["received_at", "-received_at"]


@router.get("/metrics", tags=["metrics"], responses=problems(404), **guard(Permission.METRICS_READ))
async def get_metrics(
    device_id: UUID,
    name: Annotated[
        list[str],
        Query(
            min_length=1,
            description='Metric names, e.g. "cpu_5min", "if_in_octets"; repeat for several.',
        ),
    ],
    interface_id: Annotated[
        UUID | None, Query(description="Interface metrics; omit for device-level metrics.")
    ] = None,
    from_: From = None,
    to: To = None,
    step: Annotated[
        int | None,
        Query(ge=60, description="Seconds per point; chosen automatically when omitted."),
    ] = None,
    agg: Aggregation = Aggregation.AVG,
) -> MetricSeriesSet:
    """Time series for one device (or interface). ``from`` defaults to one hour before ``to``.

    Counter metrics (octets, errors, discards) are returned as per-second rates; intervals
    that span a counter reset (device reboot) are NULL.
    """
    raise not_implemented()


@router.get("/events", tags=["events"], **guard(Permission.EVENTS_READ))
async def list_events(
    session: Session,
    device_id: UUID | None = None,
    kind: Annotated[list[EventKind] | None, Query()] = None,
    severity: Annotated[
        list[Annotated[int, Field(ge=0, le=7)]] | None,
        Query(description="Syslog severities 0-7; repeat for several."),
    ] = None,
    mnemonic: Annotated[
        list[str] | None, Query(description='e.g. "SYS-5-CONFIG_I"; repeat for several.')
    ] = None,
    from_: From = None,
    to: To = None,
    sort: EventSort = "-received_at",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> EventPage:
    """Received syslog messages and SNMP traps; ``from``/``to`` filter on ``received_at``.

    Only events from known devices are stored (the receiver drops unknown sources).
    """
    conditions: list[ColumnElement[bool]] = []
    if device_id is not None:
        conditions.append(m.Event.device_id == device_id)
    if kind:
        conditions.append(m.Event.kind.in_(kind))
    if severity:
        conditions.append(m.Event.severity.in_(severity))
    if mnemonic:
        conditions.append(m.Event.mnemonic.in_(mnemonic))
    if from_ is not None:
        conditions.append(m.Event.received_at >= from_)
    if to is not None:
        conditions.append(m.Event.received_at < to)
    total = await session.scalar(select(func.count()).select_from(m.Event).where(*conditions))
    descending = sort.startswith("-")
    order = (
        (m.Event.received_at.desc(), m.Event.id.desc())
        if descending
        else (m.Event.received_at.asc(), m.Event.id.asc())
    )
    rows = (
        await session.execute(
            select(m.Event, m.Device)
            .outerjoin(m.Device, m.Device.id == m.Event.device_id)
            .where(*conditions)
            .order_by(*order)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [
        Event(
            id=event.id,
            received_at=event.received_at,
            source_ip=ip_address(event.source_ip),
            device=DeviceRef(
                id=device.id,
                hostname=device.hostname,
                mgmt_ip=ip_address(device.mgmt_ip) if device.mgmt_ip else None,
            )
            if device
            else None,
            kind=event.kind,
            facility=event.facility,
            severity=event.severity,
            mnemonic=event.mnemonic,
            message=event.message,
            parsed=event.parsed,
        )
        for event, device in rows
    ]
    return EventPage(items=items, total=total or 0, limit=limit, offset=offset)
