"""Metrics and syslog/trap events (M3)."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from netops.api.problems import not_implemented, problems
from netops.api.schemas.monitoring import Aggregation, EventPage, MetricSeriesSet
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import DEFAULT_LIMIT, From, Limit, Offset, To
from netops.db.enums import EventKind

router = APIRouter(dependencies=AUTHENTICATED, responses=problems(401, 422, 501))

EventSort = Literal["received_at", "-received_at"]


@router.get("/metrics", tags=["metrics"], responses=problems(404))
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


@router.get("/events", tags=["events"])
async def list_events(
    device_id: UUID | None = None,
    kind: Annotated[list[EventKind] | None, Query()] = None,
    severity: Annotated[
        list[int] | None, Query(description="Syslog severities 0-7; repeat for several.")
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
    """Received syslog messages and SNMP traps; ``from``/``to`` filter on ``received_at``."""
    raise not_implemented()
