"""Authentication (M7). Contract only: tokens are not issued or checked yet."""

from enum import StrEnum
from typing import Literal

from pydantic import Field, SecretStr

from netops.api.schemas.common import ApiModel, example


class UserRole(StrEnum):
    """Proposal 7.7: Admin / Operator / Read-only."""

    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class LoginRequest(ApiModel):
    model_config = example({"username": "operator1", "password": "example-password"})

    username: str = Field(min_length=1)
    password: SecretStr = Field(min_length=1)


class Token(ApiModel):
    model_config = example({"access_token": "<JWT>", "token_type": "bearer", "expires_in": 3600})

    access_token: str
    token_type: Literal["bearer"]
    expires_in: int = Field(gt=0, description="Seconds until the token expires.")


class CurrentUser(ApiModel):
    model_config = example(
        {"username": "operator1", "display_name": "NOC Operator 1", "role": "operator"}
    )

    username: str
    display_name: str
    role: UserRole
