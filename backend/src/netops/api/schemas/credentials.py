"""Credential profiles (M7). Secret fields are write-only: requests may carry them, no
response ever does (not even masked or as a length)."""

from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, Field, SecretStr

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, Page, example
from netops.db.enums import CredentialKind, SnmpAuthProtocol, SnmpPrivProtocol

_RO = {"id": ex.CREDENTIAL_PROFILE_RO, "name": "campus-ro", "kind": "ssh"}
_OLD = {"id": ex.CREDENTIAL_PROFILE_OLD, "name": "campus-ro-2025", "kind": "ssh"}
_RO_DETAIL: dict[str, Any] = _RO | {
    "username": "netops-ro",
    "enable_secret_set": False,
    "auth_protocol": None,
    "priv_protocol": None,
    "devices": 42,
    "created_at": "2026-09-01T08:00:00Z",
    "updated_at": "2026-10-02T13:20:00Z",
}

_WRITE_ONLY = "Write-only: stored encrypted, never returned."


class CredentialProfileSummary(ApiModel):
    """A credential profile as the UI lists it. Secrets are never part of any response."""

    model_config = example(_RO)

    id: UUID
    name: str
    kind: CredentialKind


class CredentialProfilePage(Page[CredentialProfileSummary]):
    model_config = example(ex.page([_RO, _OLD]))


class CredentialProfile(ApiModel):
    """A profile for administration: everything but its secrets."""

    model_config = example(_RO_DETAIL)

    id: UUID
    name: str
    kind: CredentialKind
    username: str
    enable_secret_set: bool = Field(description="Whether an SSH enable secret is stored.")
    auth_protocol: SnmpAuthProtocol | None
    priv_protocol: SnmpPrivProtocol | None
    devices: int = Field(ge=0, description="Devices that use the profile.")
    created_at: AwareDatetime
    updated_at: AwareDatetime


class CredentialProfileCreate(ApiModel):
    """SSH: ``password`` (and optionally ``enable_secret``). SNMPv3 (authPriv only):
    ``auth_protocol``, ``auth_key``, ``priv_protocol``, ``priv_key``."""

    model_config = example(
        {"name": "campus-ro", "kind": "ssh", "username": "netops-ro", "password": "example"}
    )

    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    kind: CredentialKind
    username: str = Field(min_length=1, max_length=200)
    password: SecretStr | None = Field(
        default=None, min_length=1, max_length=1024, description=_WRITE_ONLY
    )
    enable_secret: SecretStr | None = Field(
        default=None, min_length=1, max_length=1024, description=_WRITE_ONLY
    )
    auth_protocol: SnmpAuthProtocol | None = None
    auth_key: SecretStr | None = Field(
        default=None, min_length=8, max_length=1024, description=_WRITE_ONLY
    )
    priv_protocol: SnmpPrivProtocol | None = None
    priv_key: SecretStr | None = Field(
        default=None, min_length=8, max_length=1024, description=_WRITE_ONLY
    )


class CredentialProfileUpdate(ApiModel):
    """Fields left out stay as they are; a secret is replaced only when sent."""

    model_config = example({"password": "example-new"})

    name: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    )
    username: str | None = Field(default=None, min_length=1, max_length=200)
    password: SecretStr | None = Field(
        default=None, min_length=1, max_length=1024, description=_WRITE_ONLY
    )
    enable_secret: SecretStr | None = Field(
        default=None, min_length=1, max_length=1024, description=_WRITE_ONLY
    )
    clear_enable_secret: bool = False
    auth_protocol: SnmpAuthProtocol | None = None
    auth_key: SecretStr | None = Field(
        default=None, min_length=8, max_length=1024, description=_WRITE_ONLY
    )
    priv_protocol: SnmpPrivProtocol | None = None
    priv_key: SecretStr | None = Field(
        default=None, min_length=8, max_length=1024, description=_WRITE_ONLY
    )
