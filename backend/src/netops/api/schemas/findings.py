"""Diagnosis findings (M6): root-cause candidates with their reasoning chain."""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, Field

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, DeviceRef, InterfaceRef, Page, example
from netops.db.enums import Severity


class EvidenceKind(StrEnum):
    """What an evidence reference points to."""

    COLLECTION_RUN = "collection_run"
    EVENT = "event"
    ALARM = "alarm"
    CONFIG_CHANGE = "config_change"
    METRIC_SERIES = "metric_series"


class EvidenceRef(ApiModel):
    model_config = example(
        {
            "kind": "config_change",
            "id": ex.CHANGE_TRUNK_VLAN,
            "at": ex.T_CHANGE,
            "device_id": ex.DEV_DIST_B,
            "summary": "jdoe removed VLAN 20 from the Gi1/0/3 trunk",
        }
    )

    kind: EvidenceKind
    id: str = Field(description="Id of the referenced row (UUID, or event id).")
    at: AwareDatetime = Field(description="When the referenced data was collected or happened.")
    device_id: UUID | None
    summary: str


class EvidenceStep(ApiModel):
    model_config = example(
        {
            "order": 1,
            "rule": "link.allowed_vlans_mismatch",
            "statement": "VLAN 20 is allowed on sw-b2-03 Gi1/0/49 but not on its peer "
            "dist-sw-b Gi1/0/3.",
            "references": [
                {
                    "kind": "collection_run",
                    "id": ex.RUN_IF_ACC_B2_03,
                    "at": ex.T_RUN,
                    "device_id": ex.DEV_ACC_B2_03,
                    "summary": "interfaces run on sw-b2-03",
                }
            ],
        }
    )

    order: int = Field(ge=1)
    rule: str
    statement: str
    references: list[EvidenceRef]


FINDING_EXAMPLE: dict[str, Any] = {
    "id": ex.FINDING_TRUNK_VLAN,
    "created_at": "2026-10-08T22:44:10Z",
    "incident_id": ex.INCIDENT_FLOOR_2,
    "kind": "link.allowed_vlans_mismatch",
    "severity": "major",
    "device": ex.DEVICE_REF_DIST_B,
    "interface": ex.INTERFACE_REF_DIST_DOWNLINK,
    "title": "VLAN 20 removed from the trunk to sw-b2-03",
    "explanation": "Hosts in VLAN 20 on B Block floor 2 lost their path to the gateway when "
    "VLAN 20 was removed from dist-sw-b Gi1/0/3, two minutes before the first alarm.",
    "score": 92,
    "evidence": [
        {
            "order": 1,
            "rule": "link.allowed_vlans_mismatch",
            "statement": "VLAN 20 is allowed on sw-b2-03 Gi1/0/49 but not on its peer "
            "dist-sw-b Gi1/0/3.",
            "references": [
                {
                    "kind": "collection_run",
                    "id": ex.RUN_IF_ACC_B2_03,
                    "at": ex.T_RUN,
                    "device_id": ex.DEV_ACC_B2_03,
                    "summary": "interfaces run on sw-b2-03",
                }
            ],
        },
        {
            "order": 2,
            "rule": "change.precedes_fault",
            "statement": "The change was made 1 min 53 s before the incident opened.",
            "references": [
                {
                    "kind": "config_change",
                    "id": ex.CHANGE_TRUNK_VLAN,
                    "at": ex.T_CHANGE,
                    "device_id": ex.DEV_DIST_B,
                    "summary": "jdoe removed VLAN 20 from the Gi1/0/3 trunk",
                }
            ],
        },
    ],
}
FINDING_CRC_EXAMPLE: dict[str, Any] = FINDING_EXAMPLE | {
    "id": ex.FINDING_CRC_RISING,
    "kind": "port.crc_rising",
    "severity": "minor",
    "device": ex.DEVICE_REF_ACC_B2_03,
    "interface": ex.INTERFACE_REF_ACC_UPLINK,
    "title": "CRC errors rising on sw-b2-03 Gi1/0/49",
    "explanation": "12 CRC errors in the last hour suggest a cable or SFP problem, but the "
    "link stayed up, so it does not explain the outage.",
    "score": 18,
    "evidence": [],
}


class Finding(ApiModel):
    model_config = example(FINDING_EXAMPLE)

    id: UUID
    created_at: AwareDatetime
    incident_id: UUID | None
    kind: str = Field(description='Rule that produced it, e.g. "port.crc_rising".')
    severity: Severity
    device: DeviceRef | None
    interface: InterfaceRef | None
    title: str
    explanation: str
    score: int = Field(description="Ranks candidates within an incident; higher is likelier.")
    evidence: list[EvidenceStep] = Field(description="Reasoning chain, in order.")


class FindingPage(Page[Finding]):
    model_config = example(ex.page([FINDING_EXAMPLE, FINDING_CRC_EXAMPLE]))
