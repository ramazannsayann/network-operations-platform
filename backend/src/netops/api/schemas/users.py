"""User administration (M7, admin)."""

from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, Field, SecretStr

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, Page, example
from netops.db.enums import UserRole

_OPERATOR: dict[str, Any] = {
    "id": ex.USER_OPERATOR,
    "username": "operator1",
    "display_name": "NOC Operator 1",
    "email": "operator1@example.net",
    "role": "operator",
    "is_active": True,
    "mfa_enabled": True,
    "must_change_password": False,
    "locked_until": None,
    "failed_login_count": 0,
    "last_login_at": "2026-10-11T07:58:12Z",
    "password_changed_at": "2026-09-30T09:12:00Z",
    "created_at": "2026-09-01T08:00:00Z",
}
_VIEWER: dict[str, Any] = _OPERATOR | {
    "id": ex.USER_VIEWER,
    "username": "helpdesk",
    "display_name": "Helpdesk",
    "email": None,
    "role": "viewer",
    "mfa_enabled": False,
    "last_login_at": None,
}


class User(ApiModel):
    model_config = example(_OPERATOR)

    id: UUID
    username: str
    display_name: str
    email: str | None
    role: UserRole
    is_active: bool
    mfa_enabled: bool
    must_change_password: bool
    locked_until: AwareDatetime | None
    failed_login_count: int = Field(ge=0)
    last_login_at: AwareDatetime | None
    password_changed_at: AwareDatetime
    created_at: AwareDatetime


class UserPage(Page[User]):
    model_config = example(ex.page([_OPERATOR, _VIEWER]))


class UserCreate(ApiModel):
    """The password is temporary: the user must change it at the first sign-in."""

    model_config = example(
        {
            "username": "operator2",
            "display_name": "NOC Operator 2",
            "email": "operator2@example.net",
            "role": "operator",
            "password": "a temporary pass phrase",
        }
    )

    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]+$")
    display_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")
    role: UserRole
    password: SecretStr = Field(min_length=1, max_length=1024)


class UserUpdate(ApiModel):
    """Fields left out stay as they are. Deactivating ends the user's sessions."""

    model_config = example({"role": "viewer"})

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254, pattern=r"^([^@\s]+@[^@\s]+)?$")
    role: UserRole | None = None
    is_active: bool | None = None


class PasswordReset(ApiModel):
    """Forces a password change at the next sign-in; with ``temporary_password`` it also
    replaces the password (for a user who forgot theirs). Ends the user's sessions."""

    model_config = example({"temporary_password": "a temporary pass phrase"})

    temporary_password: SecretStr | None = Field(default=None, min_length=1, max_length=1024)
