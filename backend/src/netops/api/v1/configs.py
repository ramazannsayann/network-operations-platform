"""Configuration management (M4)."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from netops.api.problems import not_implemented, problems
from netops.api.schemas.configs import (
    ConfigChangePage,
    ConfigDiff,
    ConfigVersionContent,
    ConfigVersionPage,
)
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import DEFAULT_LIMIT, From, Limit, Offset, To
from netops.db.enums import ChangeOrigin

router = APIRouter(tags=["configs"], dependencies=AUTHENTICATED, responses=problems(401, 422, 501))

VersionSort = Literal["collected_at", "-collected_at"]
ChangeSort = Literal["detected_at", "-detected_at"]


@router.get("/devices/{device_id}/configs", responses=problems(404))
async def list_device_configs(
    device_id: UUID,
    from_: From = None,
    to: To = None,
    sort: VersionSort = "-collected_at",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> ConfigVersionPage:
    """Configuration versions of a device; ``from``/``to`` filter on ``collected_at``."""
    raise not_implemented()


# Declared before /configs/{version_id} so "diff" is not taken for a version id.
@router.get("/configs/diff", responses=problems(404))
async def diff_configs(
    from_: Annotated[UUID, Query(alias="from", description="Older version id.")],
    to: Annotated[UUID, Query(description="Newer version id (may be of another device).")],
    context_lines: Annotated[int, Query(ge=0, le=50)] = 3,
) -> ConfigDiff:
    """Unified diff between two configuration versions."""
    raise not_implemented()


@router.get("/configs/{version_id}", responses=problems(404))
async def get_config_version(version_id: UUID) -> ConfigVersionContent:
    """A configuration version with its normalized text (read from Git)."""
    raise not_implemented()


@router.get("/config-changes")
async def list_config_changes(
    device_id: UUID | None = None,
    origin: Annotated[list[ChangeOrigin] | None, Query()] = None,
    username: str | None = None,
    from_: From = None,
    to: To = None,
    sort: ChangeSort = "-detected_at",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> ConfigChangePage:
    """Detected configuration changes; ``from``/``to`` filter on ``detected_at``."""
    raise not_implemented()
