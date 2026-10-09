"""Alarms and incidents (M3/M6)."""

from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, Field

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, DeviceRef, InterfaceRef, Page, example
from netops.api.schemas.configs import CHANGE_EXAMPLE, ConfigChange
from netops.api.schemas.findings import FINDING_CRC_EXAMPLE, FINDING_EXAMPLE, Finding
from netops.db.enums import AlarmState, IncidentState, Severity

ALARM_EXAMPLE: dict[str, Any] = {
    "id": ex.ALARM_VLAN_MISMATCH,
    "device": ex.DEVICE_REF_ACC_B2_03,
    "interface": ex.INTERFACE_REF_ACC_UPLINK,
    "rule_key": "link.allowed_vlans_mismatch",
    "severity": "major",
    "state": "open",
    "dedup_key": f"link.allowed_vlans_mismatch:{ex.LINK_ACC_DIST}",
    "occurrence_count": 3,
    "opened_at": ex.T_INCIDENT,
    "last_occurrence_at": ex.T_RUN,
    "acknowledged_at": None,
    "acknowledged_by": None,
    "cleared_at": None,
    "incident_id": ex.INCIDENT_FLOOR_2,
    "summary": "Allowed VLANs differ on sw-b2-03 Gi1/0/49 <-> dist-sw-b Gi1/0/3 (VLAN 20)",
    "details": {"missing_on_peer": [20], "local_allowed": [20, 30, 99], "peer_allowed": [30, 99]},
}
_ALARM_CRC: dict[str, Any] = ALARM_EXAMPLE | {
    "id": ex.ALARM_CRC_RISING,
    "rule_key": "port.crc_rising",
    "severity": "minor",
    "state": "acknowledged",
    "dedup_key": f"port.crc_rising:{ex.IF_ACC_GI1_0_49}",
    "occurrence_count": 1,
    "opened_at": "2026-10-08T21:05:00Z",
    "last_occurrence_at": "2026-10-08T21:05:00Z",
    "acknowledged_at": "2026-10-08T21:20:31Z",
    "acknowledged_by": "operator1",
    "summary": "CRC errors rising on sw-b2-03 Gi1/0/49 (12 in 60 min)",
    "details": {"crc_errors_delta": 12, "window_minutes": 60, "threshold": 10},
}


class Alarm(ApiModel):
    model_config = example(ALARM_EXAMPLE)

    id: UUID
    device: DeviceRef
    interface: InterfaceRef | None
    rule_key: str = Field(description='Rule that raised it, e.g. "interface.down".')
    severity: Severity
    state: AlarmState
    dedup_key: str
    occurrence_count: int = Field(ge=1)
    opened_at: AwareDatetime
    last_occurrence_at: AwareDatetime
    acknowledged_at: AwareDatetime | None
    acknowledged_by: str | None
    cleared_at: AwareDatetime | None
    incident_id: UUID | None
    summary: str
    details: dict[str, Any] | None = Field(description="Rule-specific context.")


class AlarmPage(Page[Alarm]):
    model_config = example(ex.page([ALARM_EXAMPLE, _ALARM_CRC]))


class AlarmAcknowledge(ApiModel):
    model_config = example({"comment": "Checking the uplink cabling on floor 2"})

    comment: str | None = Field(default=None, max_length=1000)


_INCIDENT_SUMMARY: dict[str, Any] = {
    "id": ex.INCIDENT_FLOOR_2,
    "title": "Hosts in VLAN 20 on B Block floor 2 lost connectivity",
    "state": "open",
    "opened_at": ex.T_INCIDENT,
    "resolved_at": None,
    "alarm_count": 2,
    "highest_severity": "major",
}


class IncidentSummary(ApiModel):
    model_config = example(_INCIDENT_SUMMARY)

    id: UUID
    title: str
    state: IncidentState
    opened_at: AwareDatetime
    resolved_at: AwareDatetime | None
    alarm_count: int = Field(ge=0)
    highest_severity: Severity | None


class IncidentPage(Page[IncidentSummary]):
    model_config = example(ex.page([_INCIDENT_SUMMARY]))


class Incident(IncidentSummary):
    model_config = example(
        _INCIDENT_SUMMARY
        | {
            "alarms": [ALARM_EXAMPLE, _ALARM_CRC],
            "root_cause_candidates": [FINDING_EXAMPLE, FINDING_CRC_EXAMPLE],
            "related_config_changes": [CHANGE_EXAMPLE],
            "affected_devices": [ex.DEVICE_REF_ACC_B2_03, ex.DEVICE_REF_AP_B2_01],
        }
    )

    alarms: list[Alarm]
    root_cause_candidates: list[Finding] = Field(description="Findings, best candidate first.")
    related_config_changes: list[ConfigChange] = Field(
        description="Changes on the affected devices in the window before the incident."
    )
    affected_devices: list[DeviceRef]
