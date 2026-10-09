"""Building blocks shared by every API schema: base model, list envelope, references, jobs."""

from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    IPvAnyAddress,
    StringConstraints,
)

from netops.api.problems import Problem
from netops.api.schemas import examples as ex

# Canonical string forms (ADR-0003): lower-case colon-separated MACs, 802.1Q VLAN IDs.
MacAddress = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")]
VlanId = Annotated[int, Field(ge=1, le=4094)]


class ApiModel(BaseModel):
    """Base of every API schema; built from ORM objects or dicts."""

    model_config = ConfigDict(from_attributes=True)


def example(*values: dict[str, Any]) -> ConfigDict:
    """``model_config`` for a schema with the given examples (the first one is the default)."""
    return ConfigDict(from_attributes=True, json_schema_extra={"examples": list(values)})


class Page[ItemT](ApiModel):
    """List envelope used by every collection endpoint."""

    items: list[ItemT]
    total: int = Field(ge=0, description="Number of items matching the filters, all pages.")
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


# --- References to other resources (embedded so lists need no extra round trips) ---------


class DeviceRef(ApiModel):
    model_config = example(ex.DEVICE_REF_ACC_B2_03)

    id: UUID
    hostname: str | None
    mgmt_ip: IPvAnyAddress | None


class InterfaceRef(ApiModel):
    model_config = example(ex.INTERFACE_REF_HOST_PORT)

    id: UUID
    device_id: UUID
    # As reported by the device, e.g. "Gi1/0/17".
    name: str


class LocationRef(ApiModel):
    model_config = example(ex.LOCATION_REF_FLOOR_2)

    id: UUID
    name: str
    path: str = Field(description="Full path from the top-level location, for display.")


# --- Jobs (long-running operations) ---------------------------------------------------------


class JobKind(StrEnum):
    DEVICE_REFRESH = "device_refresh"
    DISCOVERY = "discovery"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobRef(ApiModel):
    """Body of every 202 Accepted response; poll ``href`` (or watch the WebSocket)."""

    model_config = example(
        {
            "id": ex.JOB_REFRESH,
            "kind": "device_refresh",
            "status": "queued",
            "href": f"/api/v1/jobs/{ex.JOB_REFRESH}",
            "target_href": f"/api/v1/devices/{ex.DEV_ACC_B2_03}",
        }
    )

    id: UUID
    kind: JobKind
    status: JobStatus
    href: str = Field(description="URL of the job status resource.")
    target_href: str = Field(description="URL of the resource the job works on.")


class JobProgress(ApiModel):
    model_config = example({"completed": 7, "total": 11, "message": "Collecting STP state"})

    completed: int = Field(ge=0)
    total: int | None = Field(ge=0, description="NULL while the amount of work is unknown.")
    message: str | None


class Job(ApiModel):
    model_config = example(
        {
            "id": ex.JOB_REFRESH,
            "kind": "device_refresh",
            "status": "running",
            "target_href": f"/api/v1/devices/{ex.DEV_ACC_B2_03}",
            "progress": {"completed": 7, "total": 11, "message": "Collecting STP state"},
            "created_at": "2026-10-09T08:00:02Z",
            "started_at": "2026-10-09T08:00:03Z",
            "finished_at": None,
            "error": None,
        }
    )

    id: UUID
    kind: JobKind
    status: JobStatus
    target_href: str
    progress: JobProgress | None
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    finished_at: AwareDatetime | None
    error: Problem | None = Field(description="Why the job failed; NULL unless status is failed.")
