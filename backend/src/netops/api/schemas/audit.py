"""The audit log (M7, admin)."""

from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, Field, IPvAnyAddress

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, Page, example
from netops.db.enums import AuditOutcome

_LOGIN: dict[str, Any] = {
    "id": 4211,
    "at": "2026-10-11T07:58:12Z",
    "actor": {"id": ex.USER_OPERATOR, "username": "operator1"},
    "actor_ip": "10.0.0.250",
    "action": "auth.login",
    "target_type": None,
    "target_id": None,
    "outcome": "success",
    "details": {"mfa": "totp"},
}
_DENIED: dict[str, Any] = _LOGIN | {
    "id": 4215,
    "at": "2026-10-11T08:02:40Z",
    "actor": {"id": ex.USER_VIEWER, "username": "helpdesk"},
    "actor_ip": "10.0.0.251",
    "action": "access.denied",
    "target_type": "route",
    "target_id": "POST /api/v1/discovery/runs",
    "outcome": "denied",
    "details": {"permission": "discovery:run", "role": "viewer", "reason": "missing_permission"},
}


class AuditActor(ApiModel):
    model_config = example({"id": ex.USER_OPERATOR, "username": "operator1"})

    id: UUID
    username: str | None = Field(description="NULL if the user no longer exists.")


class AuditEntry(ApiModel):
    model_config = example(_LOGIN)

    id: int
    at: AwareDatetime
    actor: AuditActor | None = Field(
        description="NULL for anonymous attempts (unknown user) and the server CLI."
    )
    actor_ip: IPvAnyAddress | None
    action: str = Field(description='e.g. "auth.login", "user.update", "access.denied".')
    target_type: str | None
    target_id: str | None
    outcome: AuditOutcome
    details: dict[str, Any]


class AuditPage(Page[AuditEntry]):
    model_config = example(ex.page([_DENIED, _LOGIN], total=2))
