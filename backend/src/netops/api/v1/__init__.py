"""Version 1 of the REST API, mounted at /api/v1 (conventions: docs/adr/0003-api-conventions.md)."""

from fastapi import APIRouter

from netops.api.v1 import (
    alarms,
    auth,
    configs,
    credentials,
    devices,
    diagnosis,
    discovery,
    hosts,
    jobs,
    locations,
    monitoring,
    topology,
)

router = APIRouter(prefix="/v1")
for module in (
    auth,
    locations,
    devices,
    discovery,
    topology,
    hosts,
    diagnosis,
    alarms,
    monitoring,
    configs,
    jobs,
    credentials,
):
    router.include_router(module.router)
