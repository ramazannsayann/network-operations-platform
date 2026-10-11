"""Discovery runs (M1): CDP/LLDP breadth-first discovery from seed addresses."""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, Field, IPvAnyAddress, IPvAnyNetwork

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, DeviceRef, Page, example
from netops.db.enums import DiscoveryItemStatus, DiscoverySource, JobStatus


class SkipReason(StrEnum):
    """Why discovery did not crawl a neighbour (proposal 7.1)."""

    OUT_OF_SCOPE = "out_of_scope"  # management address outside the allowed subnets
    NO_MGMT_IP = "no_mgmt_ip"
    UNREACHABLE = "unreachable"
    AUTH_FAILED = "auth_failed"  # both credential profiles were rejected
    UNSUPPORTED_PLATFORM = "unsupported_platform"


class DiscoveryRunCreate(ApiModel):
    model_config = example(
        {
            "seeds": ["10.0.0.1"],
            "allowed_subnets": ["10.0.0.0/16"],
            "credential_profile_ids": [ex.CREDENTIAL_PROFILE_RO],
        }
    )

    seeds: list[IPvAnyAddress] = Field(min_length=1, description="Where the crawl starts.")
    allowed_subnets: list[IPvAnyNetwork] = Field(
        min_length=1, description="Neighbours outside these are reported but not crawled."
    )
    credential_profile_ids: list[UUID] = Field(
        min_length=1,
        description="SSH credential profiles to try, in order. At most two logins per device: "
        "the profile that worked on it before first, then these.",
    )


class DiscoveryProgress(ApiModel):
    model_config = example({"queued": 3, "scanned": 14, "found": 12, "skipped": 2, "errors": 1})

    queued: int = Field(ge=0, description="Addresses waiting in the BFS queue.")
    scanned: int = Field(ge=0)
    found: int = Field(ge=0, description="Devices found so far (new or already known).")
    skipped: int = Field(ge=0)
    errors: int = Field(ge=0)


class DiscoveredDevice(ApiModel):
    model_config = example(
        {"device": ex.DEVICE_REF_ACC_B2_03, "discovered_via": "cdp", "is_new": False}
    )

    device: DeviceRef
    discovered_via: DiscoverySource
    is_new: bool = Field(description="False if the device was already in the inventory.")


class SkippedNeighbor(ApiModel):
    model_config = example(
        {
            "name": "isp-ce-1",
            "mgmt_ip": "198.51.100.1",
            "platform": "cisco ISR4331/K9",
            "seen_from": ex.DEVICE_REF_CORE_1,
            "local_interface": "Gi1/0/48",
            "reason": "out_of_scope",
        }
    )

    name: str | None
    mgmt_ip: IPvAnyAddress | None
    platform: str | None
    seen_from: DeviceRef
    local_interface: str
    reason: SkipReason


class DiscoveryError(ApiModel):
    model_config = example(
        {
            "target": "10.0.0.31",
            "message": "SSH connection timed out after 10 s",
            "occurred_at": "2026-10-09T08:01:44Z",
        }
    )

    target: IPvAnyAddress
    message: str
    occurred_at: AwareDatetime


_ITEM: dict[str, Any] = {
    "address": "10.0.0.23",
    "hop": 2,
    "status": "discovered",
    "device": ex.DEVICE_REF_ACC_B2_03,
    "seen_from": ex.DEVICE_REF_DIST_B,
    "local_interface": "GigabitEthernet1/0/3",
    "neighbor_name": "sw-b2-03.campus.example.net",
    "platform": "cisco WS-C2960X-48FPD-L",
    "attempts": 1,
    "is_new": False,
    "error": None,
    "occurred_at": "2026-10-09T08:01:12Z",
}


class DiscoveryRunItem(ApiModel):
    """What the run did with one address (or address-less neighbour)."""

    model_config = example(_ITEM)

    address: IPvAnyAddress | None
    hop: int = Field(ge=0, description="BFS level: 0 for seeds.")
    status: DiscoveryItemStatus
    device: DeviceRef | None = Field(
        description="The device found, the one a duplicate address belongs to, or the "
        "placeholder recorded for a skipped or failed address."
    )
    seen_from: DeviceRef | None = Field(description="The device whose CDP/LLDP pointed here.")
    local_interface: str | None = Field(description="Its interface towards this neighbour.")
    neighbor_name: str | None
    platform: str | None
    attempts: int = Field(ge=0, le=2, description="Logins tried (at most two).")
    is_new: bool
    error: str | None
    occurred_at: AwareDatetime


_REQUEST: dict[str, Any] = {
    "seeds": ["10.0.0.1"],
    "allowed_subnets": ["10.0.0.0/16"],
    "credential_profile_ids": [ex.CREDENTIAL_PROFILE_RO],
}
_SUMMARY: dict[str, Any] = {
    "id": ex.DISCOVERY_RUN,
    "job_id": ex.JOB_DISCOVERY,
    "status": "running",
    "requested_at": "2026-10-09T08:00:30Z",
    "started_at": "2026-10-09T08:00:31Z",
    "finished_at": None,
    "progress": {"queued": 3, "scanned": 14, "found": 12, "skipped": 2, "errors": 1},
}


class DiscoveryRunSummary(ApiModel):
    model_config = example(_SUMMARY)

    id: UUID
    job_id: UUID
    status: JobStatus
    requested_at: AwareDatetime
    started_at: AwareDatetime | None
    finished_at: AwareDatetime | None
    progress: DiscoveryProgress


class DiscoveryRun(DiscoveryRunSummary):
    model_config = example(
        _SUMMARY
        | {
            "request": _REQUEST,
            "found_devices": [
                {"device": ex.DEVICE_REF_CORE_1, "discovered_via": "seed", "is_new": False},
                {"device": ex.DEVICE_REF_ACC_B2_03, "discovered_via": "cdp", "is_new": False},
            ],
            "skipped_neighbors": [
                {
                    "name": "isp-ce-1",
                    "mgmt_ip": "198.51.100.1",
                    "platform": "cisco ISR4331/K9",
                    "seen_from": ex.DEVICE_REF_CORE_1,
                    "local_interface": "Gi1/0/48",
                    "reason": "out_of_scope",
                }
            ],
            "errors": [
                {
                    "target": "10.0.0.31",
                    "message": "SSH connection timed out after 10 s",
                    "occurred_at": "2026-10-09T08:01:44Z",
                }
            ],
            "items": [_ITEM],
        }
    )

    request: DiscoveryRunCreate
    found_devices: list[DiscoveredDevice]
    skipped_neighbors: list[SkippedNeighbor]
    errors: list[DiscoveryError]
    items: list[DiscoveryRunItem] = Field(
        description="Every address the run dealt with, in BFS order, with its outcome."
    )


class DiscoveryRunPage(Page[DiscoveryRunSummary]):
    model_config = example(ex.page([_SUMMARY]))
