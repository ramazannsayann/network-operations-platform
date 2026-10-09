"""Metrics and syslog/trap events (M3)."""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, IPvAnyAddress

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, DeviceRef, Page, example
from netops.db.enums import EventKind


class Aggregation(StrEnum):
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    LAST = "last"


class MetricPoint(ApiModel):
    model_config = example({"time": "2026-10-09T07:50:00Z", "value": 1843200.0})

    time: AwareDatetime = Field(description="Start of the step.")
    value: float | None = Field(description="NULL where there is no data (e.g. counter reset).")


_SERIES: dict[str, Any] = {
    "device_id": ex.DEV_ACC_B2_03,
    "interface_id": ex.IF_ACC_GI1_0_49,
    "name": "if_in_octets",
    "unit": "octets/s",
    "points": [
        {"time": "2026-10-09T07:45:00Z", "value": 1712640.0},
        {"time": "2026-10-09T07:50:00Z", "value": 1843200.0},
        {"time": "2026-10-09T07:55:00Z", "value": 1650310.5},
    ],
}


class MetricSeries(ApiModel):
    model_config = example(_SERIES)

    device_id: UUID
    interface_id: UUID | None
    name: str
    unit: str | None
    points: list[MetricPoint]


class MetricSeriesSet(ApiModel):
    model_config = example(
        {
            "from": "2026-10-09T07:45:00Z",
            "to": ex.T_NOW,
            "step_seconds": 300,
            "aggregation": "avg",
            "series": [_SERIES],
        }
    ) | ConfigDict(validate_by_name=True, validate_by_alias=True)

    from_: AwareDatetime = Field(alias="from", serialization_alias="from")
    to: AwareDatetime
    step_seconds: int = Field(gt=0)
    aggregation: Aggregation
    series: list[MetricSeries]


EVENT_EXAMPLE: dict[str, Any] = {
    "id": 884213,
    "received_at": "2026-10-08T22:41:13Z",
    "source_ip": "10.0.0.11",
    "device": ex.DEVICE_REF_DIST_B,
    "kind": "syslog",
    "facility": 23,
    "severity": 5,
    "mnemonic": "SYS-5-CONFIG_I",
    "message": "Configured from console by jdoe on vty0 (10.0.0.250)",
    "parsed": {"user": "jdoe", "line": "vty0", "source_ip": "10.0.0.250"},
}
_EVENT_UPDOWN: dict[str, Any] = EVENT_EXAMPLE | {
    "id": 884198,
    "received_at": "2026-10-08T21:04:51Z",
    "source_ip": "10.0.0.23",
    "device": ex.DEVICE_REF_ACC_B2_03,
    "severity": 3,
    "mnemonic": "LINK-3-UPDOWN",
    "message": "Interface GigabitEthernet1/0/49, changed state to down",
    "parsed": {"interface": "GigabitEthernet1/0/49", "state": "down"},
}


class Event(ApiModel):
    model_config = example(EVENT_EXAMPLE)

    id: int
    received_at: AwareDatetime
    source_ip: IPvAnyAddress
    device: DeviceRef | None = Field(description="NULL if the source is not a known device.")
    kind: EventKind
    facility: int | None = Field(ge=0, le=23, description="Syslog facility code (RFC 5424).")
    severity: int | None = Field(ge=0, le=7, description="0 emergency ... 7 debug (RFC 5424).")
    mnemonic: str | None
    message: str
    parsed: dict[str, Any] | None


class EventPage(Page[Event]):
    model_config = example(ex.page([EVENT_EXAMPLE, _EVENT_UPDOWN], total=1284))
