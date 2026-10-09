"""Credential profiles (minimal M7): names for choosing them, never their secrets."""

from uuid import UUID

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, Page, example
from netops.db.enums import CredentialKind

_RO = {"id": ex.CREDENTIAL_PROFILE_RO, "name": "campus-ro", "kind": "ssh"}
_OLD = {"id": ex.CREDENTIAL_PROFILE_OLD, "name": "campus-ro-2025", "kind": "ssh"}


class CredentialProfileSummary(ApiModel):
    """A credential profile as the UI lists it. Secrets are never part of any response."""

    model_config = example(_RO)

    id: UUID
    name: str
    kind: CredentialKind


class CredentialProfilePage(Page[CredentialProfileSummary]):
    model_config = example(ex.page([_RO, _OLD]))
