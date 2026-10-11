"""Authentication (M7): sign-in with password and TOTP, sessions, the signed-in account."""

from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, IPvAnyAddress, SecretStr, model_validator

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, Page, example
from netops.auth.rbac import Permission, permissions_of
from netops.auth.service import Requirement
from netops.db.enums import UserRole

__all__ = ["UserRole"]

_ACCESS: dict[str, Any] = {
    "status": "authenticated",
    "access_token": "<JWT>",
    "token_type": "bearer",
    "expires_in": 900,
    "requirements": [],
}


class LoginRequest(ApiModel):
    model_config = example({"username": "operator1", "password": "example-password"})

    username: str = Field(min_length=1, max_length=200)
    password: SecretStr = Field(min_length=1, max_length=1024)


class LoginResponse(ApiModel):
    """``authenticated``: the access token (the refresh token is set as an HttpOnly cookie
    scoped to /api/v1/auth). ``mfa_required``: send a code with ``mfa_challenge`` to
    POST /auth/mfa/verify within ``expires_in`` seconds."""

    model_config = example(_ACCESS)

    status: Literal["authenticated", "mfa_required"]
    access_token: str | None = None
    token_type: Literal["bearer"] | None = None
    expires_in: int = Field(gt=0, description="Seconds until the token (or challenge) expires.")
    mfa_challenge: str | None = None
    requirements: list[Requirement] = Field(
        default_factory=list,
        description="What the session must do before anything but its own account opens: "
        "change the password, enroll in MFA.",
    )


class MfaVerifyRequest(ApiModel):
    model_config = example({"mfa_challenge": "<challenge>", "code": "492039"})

    mfa_challenge: str = Field(min_length=1, max_length=2048)
    code: str | None = Field(default=None, max_length=12, description="6-digit TOTP code.")
    recovery_code: str | None = Field(
        default=None, max_length=32, description="One of the recovery codes, instead of code."
    )

    @model_validator(mode="after")
    def _one_code(self) -> "MfaVerifyRequest":
        if bool(self.code) == bool(self.recovery_code):
            raise ValueError("send either code or recovery_code")
        return self


class AccessToken(ApiModel):
    model_config = example({k: v for k, v in _ACCESS.items() if k != "status"})

    access_token: str
    token_type: Literal["bearer"]
    expires_in: int = Field(gt=0)
    requirements: list[Requirement]


class CurrentUser(ApiModel):
    model_config = example(
        {
            "id": ex.USER_OPERATOR,
            "username": "operator1",
            "display_name": "NOC Operator 1",
            "email": "operator1@example.net",
            "role": "operator",
            "permissions": sorted(p.value for p in permissions_of(UserRole.OPERATOR)),
            "mfa_enabled": True,
            "mfa_required": True,
            "requirements": [],
            "session_id": ex.SESSION_1,
            "last_login_at": "2026-10-11T07:58:12Z",
            "password_changed_at": "2026-09-30T09:12:00Z",
        }
    )

    id: UUID
    username: str
    display_name: str
    email: str | None
    role: UserRole
    permissions: list[Permission]
    mfa_enabled: bool
    mfa_required: bool = Field(description="Whether the MFA policy applies to this role.")
    requirements: list[Requirement]
    session_id: UUID
    last_login_at: AwareDatetime | None
    password_changed_at: AwareDatetime


class PasswordChange(ApiModel):
    model_config = example(
        {"current_password": "example-current", "new_password": "a long new pass phrase"}
    )

    current_password: SecretStr = Field(min_length=1, max_length=1024)
    new_password: SecretStr = Field(min_length=1, max_length=1024)


class MfaEnrollment(ApiModel):
    """A pending TOTP secret: add it to an authenticator app, then confirm with a code."""

    model_config = example(
        {
            "secret": "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
            "otpauth_uri": "otpauth://totp/NetOps:operator1?secret=JBSWY3DPEHPK3PXP"
            "JBSWY3DPEHPK3PXP&issuer=NetOps",
            "qr_svg": "data:image/svg+xml,...",
        }
    )

    secret: str = Field(description="Base32 secret, for manual entry.")
    otpauth_uri: str
    qr_svg: str = Field(description="The otpauth URI as a QR code (SVG data URI).")


class MfaCode(ApiModel):
    model_config = example({"code": "492039"})

    code: str = Field(min_length=6, max_length=12)


class RecoveryCodes(ApiModel):
    """Shown once: the platform stores only their hashes."""

    model_config = example({"recovery_codes": ["k7mfp-2wq9x", "r3hjt-8vbna"]})

    recovery_codes: list[str]


class MfaDisable(ApiModel):
    model_config = example({"password": "example-password", "code": "492039"})

    password: SecretStr = Field(min_length=1, max_length=1024)
    code: str | None = Field(default=None, max_length=12)
    recovery_code: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _one_code(self) -> "MfaDisable":
        if bool(self.code) == bool(self.recovery_code):
            raise ValueError("send either code or recovery_code")
        return self


_SESSION: dict[str, Any] = {
    "id": ex.SESSION_1,
    "started_at": "2026-10-11T07:58:12Z",
    "last_used_at": "2026-10-11T09:43:05Z",
    "expires_at": "2026-10-11T21:43:05Z",
    "ip": "10.0.0.250",
    "user_agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0",
    "current": True,
}


class SessionInfo(ApiModel):
    """A sign-in that can still be refreshed (a refresh token family)."""

    model_config = example(_SESSION)

    id: UUID
    started_at: AwareDatetime
    last_used_at: AwareDatetime
    expires_at: AwareDatetime
    ip: IPvAnyAddress | None
    user_agent: str | None
    current: bool


class SessionPage(Page[SessionInfo]):
    model_config = example(ex.page([_SESSION]))
