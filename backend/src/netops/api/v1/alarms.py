"""Alarms, incidents and findings (M3/M6)."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from netops.api.problems import not_implemented, problems
from netops.api.schemas.alarms import Alarm, AlarmAcknowledge, AlarmPage, Incident, IncidentPage
from netops.api.schemas.findings import FindingPage
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import DEFAULT_LIMIT, From, Limit, Offset, To
from netops.db.enums import AlarmState, IncidentState, Severity

router = APIRouter(dependencies=AUTHENTICATED, responses=problems(401, 422, 501))

AlarmSort = Literal["opened_at", "-opened_at", "last_occurrence_at", "-last_occurrence_at"]
IncidentSort = Literal["opened_at", "-opened_at"]
FindingSort = Literal["score", "-score", "created_at", "-created_at"]


@router.get("/alarms", tags=["alarms"])
async def list_alarms(
    state: Annotated[list[AlarmState] | None, Query()] = None,
    severity: Annotated[list[Severity] | None, Query()] = None,
    device_id: UUID | None = None,
    incident_id: UUID | None = None,
    from_: From = None,
    to: To = None,
    sort: AlarmSort = "-opened_at",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> AlarmPage:
    """Alarms; ``from``/``to`` filter on ``opened_at``."""
    raise not_implemented()


@router.get("/alarms/{alarm_id}", tags=["alarms"], responses=problems(404))
async def get_alarm(alarm_id: UUID) -> Alarm:
    raise not_implemented()


@router.post("/alarms/{alarm_id}/acknowledge", tags=["alarms"], responses=problems(404, 409))
async def acknowledge_alarm(alarm_id: UUID, body: AlarmAcknowledge | None = None) -> Alarm:
    """Acknowledge an open alarm as the calling user. 409 if it is already cleared."""
    raise not_implemented()


@router.get("/incidents", tags=["incidents"])
async def list_incidents(
    state: Annotated[list[IncidentState] | None, Query()] = None,
    from_: From = None,
    to: To = None,
    sort: IncidentSort = "-opened_at",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> IncidentPage:
    """Incidents; ``from``/``to`` filter on ``opened_at``."""
    raise not_implemented()


@router.get("/incidents/{incident_id}", tags=["incidents"], responses=problems(404))
async def get_incident(incident_id: UUID) -> Incident:
    """An incident with its alarms, ranked root-cause candidates and related config changes."""
    raise not_implemented()


@router.get("/findings", tags=["findings"])
async def list_findings(
    incident_id: UUID | None = None,
    device_id: UUID | None = None,
    kind: Annotated[
        list[str] | None, Query(description='Rule keys, e.g. "port.crc_rising".')
    ] = None,
    sort: FindingSort = "-score",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> FindingPage:
    """Diagnosis findings, each with its evidence chain."""
    raise not_implemented()
