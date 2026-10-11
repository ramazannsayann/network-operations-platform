"""M7 end to end against the test database: sign-in, lockout, rate limits, MFA, sessions
(refresh rotation, reuse detection, logout), forced flows, user and credential
administration, RBAC with real tokens, and the audit log (including that the database
refuses to change it)."""

import json
import secrets
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from netops.auth import service, tokens
from netops.core.settings import get_settings
from netops.db import models as m
from netops.db.enums import UserRole
from tests.integration.support import ADMIN, Recorder, add_user, run, sign_in

pytestmark = pytest.mark.integration

# Random per run: no password literal in the repository.
PASSWORD = "pass phrase for tests " + secrets.token_hex(4)
OTHER = "another pass phrase " + secrets.token_hex(4)


@pytest.fixture
def api_client(api: tuple[TestClient, Recorder]) -> TestClient:
    """The admin's client (see conftest.api)."""
    return api[0]


@pytest.fixture
def anonymous(api: tuple[TestClient, Recorder]) -> Iterator[TestClient]:
    """Another client of the same application, without a token or cookies."""
    client, _ = api
    with TestClient(client.app) as fresh:
        yield fresh


def new_client(api_client: TestClient) -> TestClient:
    return TestClient(api_client.app)


def user(name: str, role: UserRole = UserRole.OPERATOR, **values: Any) -> uuid.UUID:
    return run(lambda session: add_user(session, name, role, PASSWORD, **values))


def audit_entries(action: str | None = None, **where: Any) -> list[m.AuditLogEntry]:
    async def load(session: AsyncSession) -> list[m.AuditLogEntry]:
        stmt = select(m.AuditLogEntry).order_by(m.AuditLogEntry.id)
        if action:
            stmt = stmt.where(m.AuditLogEntry.action == action)
        for key, value in where.items():
            stmt = stmt.where(getattr(m.AuditLogEntry, key) == value)
        return list(await session.scalars(stmt))

    return run(load)


def db_user(user_id: uuid.UUID) -> m.User:
    async def load(session: AsyncSession) -> m.User:
        found = await session.get(m.User, user_id)
        assert found is not None
        return found

    return run(load)


def login(client: TestClient, username: str, password: str) -> Any:
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


# --- sign-in --------------------------------------------------------------------------------


def test_login_sets_a_strict_refresh_cookie_and_returns_an_access_token(
    anonymous: TestClient,
) -> None:
    user_id = user("op.one")
    response = login(anonymous, "OP.One", PASSWORD)  # usernames are case-insensitive
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "authenticated"
    assert body["expires_in"] == 900
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("netops_refresh=")
    for attribute in ("HttpOnly", "Path=/api/v1/auth", "SameSite=strict"):
        assert attribute in cookie
    assert "Secure" not in cookie  # plain HTTP in tests; "auto" sets it over HTTPS
    assert body["access_token"] not in cookie
    me = anonymous.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    ).json()
    assert me["id"] == str(user_id)
    assert me["role"] == "operator"
    assert "discovery:run" in me["permissions"]
    assert "users:manage" not in me["permissions"]
    (entry,) = audit_entries("auth.login", actor_user_id=user_id, outcome="success")
    assert entry.details["mfa"] == "none"
    assert db_user(user_id).last_login_at is not None


def test_every_login_failure_looks_the_same(anonymous: TestClient) -> None:
    active = user("op.fail")
    inactive = user("op.gone")

    async def deactivate(session: AsyncSession) -> None:
        await session.execute(update(m.User).where(m.User.id == inactive).values(is_active=False))
        await session.commit()

    run(deactivate)
    answers = [
        login(anonymous, "nobody-here", PASSWORD),
        login(anonymous, "op.fail", "wrong pass phrase here"),
        login(anonymous, "op.gone", PASSWORD),
    ]
    assert {r.status_code for r in answers} == {401}
    assert len({json.dumps(r.json(), sort_keys=True) for r in answers}) == 1
    assert answers[0].json()["detail"] == service.GENERIC_FAILURE
    reasons = {e.details["reason"] for e in audit_entries("auth.login", outcome="failed")}
    assert {"unknown_user", "wrong_password", "inactive"} <= reasons
    assert db_user(active).failed_login_count == 1


def test_progressive_lockout_and_admin_unlock(
    api_client: TestClient, anonymous: TestClient
) -> None:
    user_id = user("op.lock")
    for _ in range(5):
        assert login(anonymous, "op.lock", "wrong pass phrase here").status_code == 401
    locked = db_user(user_id)
    assert locked.failed_login_count == 5
    assert locked.locked_until is not None
    assert timedelta(seconds=55) < locked.locked_until - datetime.now(UTC) <= timedelta(seconds=60)
    # Even the right password is refused while locked, with the same answer.
    response = login(anonymous, "op.lock", PASSWORD)
    assert response.status_code == 401
    assert response.json()["detail"] == service.GENERIC_FAILURE
    (lock,) = audit_entries("auth.lockout", actor_user_id=user_id)
    assert lock.details == {"failures": 5, "locked_seconds": 60}
    assert audit_entries("auth.login", actor_user_id=user_id)[-1].details["reason"] == "locked"

    # Each further failure after a lock doubles it.
    async def expire(session: AsyncSession) -> None:
        await session.execute(
            update(m.User).where(m.User.id == user_id).values(locked_until=datetime.now(UTC))
        )
        await session.commit()

    run(expire)
    assert login(anonymous, "op.lock", "wrong pass phrase here").status_code == 401
    assert audit_entries("auth.lockout", actor_user_id=user_id)[-1].details["locked_seconds"] == 120

    assert api_client.post(f"/api/v1/users/{user_id}/unlock").status_code == 204
    assert login(anonymous, "op.lock", PASSWORD).status_code == 200
    assert db_user(user_id).failed_login_count == 0
    assert audit_entries("user.unlock", target_id=str(user_id))


def test_login_is_rate_limited_per_address(anonymous: TestClient) -> None:
    limit = get_settings().auth_rate_limit_per_ip
    statuses = [login(anonymous, f"probe{i}", PASSWORD).status_code for i in range(limit + 1)]
    # The fixture's own sign-in was the first request from this address.
    assert statuses[: limit - 1] == [401] * (limit - 1)
    assert statuses[limit - 1 :] == [429, 429]
    response = login(anonymous, "probe", PASSWORD)
    assert response.json()["type"] == "urn:netops:problem:rate-limited"
    assert int(response.headers["retry-after"]) > 0
    assert audit_entries("auth.rate_limited")
    # MFA verification has a limit of its own.
    assert (
        anonymous.post(
            "/api/v1/auth/mfa/verify", json={"mfa_challenge": "x", "code": "123456"}
        ).status_code
        == 401
    )


# --- MFA ------------------------------------------------------------------------------------


@pytest.fixture
def mfa_policy(api: tuple[TestClient, Recorder], monkeypatch: pytest.MonkeyPatch) -> None:
    """MFA required for operators (the signed-in test admin stays exempt)."""
    monkeypatch.setenv("AUTH_MFA_REQUIRED_ROLES", "operator")
    get_settings.cache_clear()


def enroll(client: TestClient, at: datetime | None = None) -> tuple[str, list[str]]:
    started = client.post("/api/v1/auth/mfa/enroll")
    assert started.status_code == 200, started.text
    enrollment = started.json()
    assert enrollment["otpauth_uri"].startswith("otpauth://totp/NetOps:")
    assert enrollment["qr_svg"].startswith("data:image/svg+xml")
    secret = enrollment["secret"]
    code = pyotp.TOTP(secret).at(at or datetime.now(UTC))
    confirmed = client.post("/api/v1/auth/mfa/enroll/confirm", json={"code": code})
    assert confirmed.status_code == 200, confirmed.text
    codes: list[str] = confirmed.json()["recovery_codes"]
    return secret, codes


def test_forced_enrollment_then_login_with_totp_and_recovery_codes(
    mfa_policy: None, anonymous: TestClient
) -> None:
    user_id = user("op.mfa")
    first = login(anonymous, "op.mfa", PASSWORD).json()
    assert first["requirements"] == ["mfa_enrollment"]
    (signed_in,) = audit_entries("auth.login", actor_user_id=user_id, outcome="success")
    assert signed_in.details["requirements"] == ["mfa_enrollment"]
    anonymous.headers["Authorization"] = f"Bearer {first['access_token']}"
    blocked = anonymous.get("/api/v1/devices")
    assert blocked.status_code == 403
    assert blocked.json()["type"] == "urn:netops:problem:mfa-enrollment-required"
    assert audit_entries("access.denied", actor_user_id=user_id)[-1].details["reason"] == (
        "mfa_enrollment"
    )
    # A wrong first code does not enable MFA.
    anonymous.post("/api/v1/auth/mfa/enroll")
    assert (
        anonymous.post("/api/v1/auth/mfa/enroll/confirm", json={"code": "000000"}).status_code
        == 422
    )
    secret, recovery = enroll(anonymous, datetime.now(UTC) - timedelta(seconds=30))
    assert len(recovery) == 10
    assert anonymous.get("/api/v1/devices").status_code == 200
    assert anonymous.get("/api/v1/auth/me").json()["requirements"] == []
    assert audit_entries("auth.mfa.enroll", actor_user_id=user_id, outcome="success")

    # Sign in again: password, then the second factor.
    client = new_client(anonymous)
    step = login(client, "op.mfa", PASSWORD).json()
    assert step["status"] == "mfa_required"
    assert step["access_token"] is None
    challenge = step["mfa_challenge"]
    code = pyotp.TOTP(secret).now()
    verified = client.post(
        "/api/v1/auth/mfa/verify", json={"mfa_challenge": challenge, "code": code}
    )
    assert verified.status_code == 200, verified.text
    assert "netops_refresh=" in verified.headers["set-cookie"]
    # The same code cannot be used twice, not even within its 30 seconds.
    replay = client.post("/api/v1/auth/mfa/verify", json={"mfa_challenge": challenge, "code": code})
    assert replay.status_code == 401
    # A recovery code works once.
    ok = client.post(
        "/api/v1/auth/mfa/verify", json={"mfa_challenge": challenge, "recovery_code": recovery[0]}
    )
    assert ok.status_code == 200
    again = client.post(
        "/api/v1/auth/mfa/verify", json={"mfa_challenge": challenge, "recovery_code": recovery[0]}
    )
    assert again.status_code == 401
    failures = audit_entries("auth.mfa.verify", actor_user_id=user_id, outcome="failed")
    assert len(failures) == 2
    logins = audit_entries("auth.login", actor_user_id=user_id, outcome="success")
    assert [e.details["mfa"] for e in logins[-2:]] == ["totp", "recovery_code"]
    assert logins[-1].details["recovery_codes_left"] == 9
    # A challenge is not an access token, and an access token is not a challenge.
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {challenge}"}).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/mfa/verify",
            json={"mfa_challenge": verified.json()["access_token"], "code": "123456"},
        ).status_code
        == 401
    )


def test_mfa_failures_count_towards_the_lockout(mfa_policy: None, anonymous: TestClient) -> None:
    user_id = user("op.guess")
    first = login(anonymous, "op.guess", PASSWORD).json()
    anonymous.headers["Authorization"] = f"Bearer {first['access_token']}"
    enroll(anonymous)
    client = new_client(anonymous)
    challenge = login(client, "op.guess", PASSWORD).json()["mfa_challenge"]
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/mfa/verify", json={"mfa_challenge": challenge, "code": "000000"}
        )
        assert response.status_code == 401
    assert db_user(user_id).locked_until is not None
    # The password alone no longer resets the counter (it needs the second factor).
    assert login(client, "op.guess", PASSWORD).status_code == 401


def test_disable_and_admin_reset_of_mfa(
    mfa_policy: None, api_client: TestClient, anonymous: TestClient
) -> None:
    user_id = user("op.phone")
    first = login(anonymous, "op.phone", PASSWORD).json()
    anonymous.headers["Authorization"] = f"Bearer {first['access_token']}"
    _, recovery = enroll(anonymous, datetime.now(UTC) - timedelta(seconds=30))
    wrong = anonymous.post(
        "/api/v1/auth/mfa/disable", json={"password": "wrong pass phrase", "code": "000000"}
    )
    assert wrong.status_code == 422
    disabled = anonymous.post(
        "/api/v1/auth/mfa/disable", json={"password": PASSWORD, "recovery_code": recovery[1]}
    )
    assert disabled.status_code == 204
    assert not db_user(user_id).mfa_enabled
    # MFA is required for operators: the session is back to enrollment only.
    assert anonymous.get("/api/v1/devices").status_code == 403
    enroll(anonymous)
    assert anonymous.get("/api/v1/devices").status_code == 200

    assert api_client.post(f"/api/v1/users/{user_id}/reset-mfa").status_code == 204
    reset = db_user(user_id)
    assert not reset.mfa_enabled
    assert reset.mfa_secret is None
    assert anonymous.get("/api/v1/devices").status_code == 401  # sessions ended
    (entry,) = audit_entries("auth.mfa.reset", target_id=str(user_id))
    assert entry.actor_user_id is not None
    assert audit_entries("auth.mfa.disable", actor_user_id=user_id, outcome="success")
    assert audit_entries("auth.mfa.disable", actor_user_id=user_id, outcome="failed")


# --- sessions -------------------------------------------------------------------------------


def test_refresh_rotates_and_reuse_ends_the_session(anonymous: TestClient) -> None:
    user_id = user("op.refresh")
    first = login(anonymous, "op.refresh", PASSWORD)
    old_cookie = anonymous.cookies.get("netops_refresh")
    assert old_cookie
    refreshed = anonymous.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    new_cookie = anonymous.cookies.get("netops_refresh")
    assert new_cookie
    assert new_cookie != old_cookie
    access = refreshed.json()["access_token"]
    assert access != first.json()["access_token"]
    assert (
        anonymous.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code
        == 200
    )

    # The old token again: copied, so the whole family is revoked.
    thief = new_client(anonymous)
    stolen = thief.post("/api/v1/auth/refresh", headers={"Cookie": f"netops_refresh={old_cookie}"})
    assert stolen.status_code == 401
    (reuse,) = audit_entries("auth.refresh.reuse", actor_user_id=user_id)
    assert reuse.details["revoked_count"] == 1
    assert anonymous.post("/api/v1/auth/refresh").status_code == 401  # the new one is dead too
    assert (
        anonymous.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code
        == 401
    ), "access tokens of a revoked session stop working at once"
    assert anonymous.post("/api/v1/auth/refresh").status_code == 401  # no cookie at all now


def test_logout_and_sessions(anonymous: TestClient) -> None:
    user("op.out")
    phone = new_client(anonymous)
    sign_in(phone, "op.out", PASSWORD)
    sign_in(anonymous, "op.out", PASSWORD)
    sessions = anonymous.get("/api/v1/auth/sessions").json()["items"]
    assert len(sessions) == 2
    current = [s for s in sessions if s["current"]]
    other = [s for s in sessions if not s["current"]]
    assert len(current) == len(other) == 1
    assert current[0]["user_agent"] == "testclient"
    # End the other one from here.
    assert anonymous.delete(f"/api/v1/auth/sessions/{other[0]['id']}").status_code == 204
    assert phone.get("/api/v1/auth/me").status_code == 401
    assert anonymous.delete(f"/api/v1/auth/sessions/{uuid.uuid4()}").status_code == 404

    response = anonymous.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert anonymous.get("/api/v1/auth/me").status_code == 401
    assert anonymous.post("/api/v1/auth/refresh").status_code == 401
    assert audit_entries("auth.logout")
    assert audit_entries("auth.session.revoke")


def test_session_lifetime_is_capped(anonymous: TestClient) -> None:
    """A family older than AUTH_SESSION_MAX_DAYS cannot be refreshed."""
    user_id = user("op.old")
    login(anonymous, "op.old", PASSWORD)

    async def age(session: AsyncSession) -> None:
        await session.execute(
            update(m.RefreshToken)
            .where(m.RefreshToken.user_id == user_id)
            .values(created_at=datetime.now(UTC) - timedelta(days=8))
        )
        await session.commit()

    run(age)
    assert anonymous.post("/api/v1/auth/refresh").status_code == 401


def test_tokens_signed_with_another_key_or_expired_are_rejected(api_client: TestClient) -> None:
    me = api_client.get("/api/v1/auth/me").json()
    settings = get_settings()
    now = datetime.now(UTC)
    other = settings.model_copy(
        update={"auth_signing_key": type(settings.auth_signing_key)("z" * 40)}
    )
    forged, _ = tokens.issue_access_token(
        uuid.UUID(me["id"]), uuid.UUID(me["session_id"]), other, now
    )
    expired, _ = tokens.issue_access_token(
        uuid.UUID(me["id"]), uuid.UUID(me["session_id"]), settings, now - timedelta(hours=2)
    )
    for token in (forged, expired, forged[:-2] + "xx"):
        response = api_client.get("/api/v1/devices", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


# --- password changes -----------------------------------------------------------------------


def test_temporary_password_must_be_changed_first(
    api_client: TestClient, anonymous: TestClient
) -> None:
    created = api_client.post(
        "/api/v1/users",
        json={
            "username": "Helpdesk.New",
            "display_name": "Helpdesk New",
            "role": "viewer",
            "password": PASSWORD,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["username"] == "helpdesk.new"
    assert created.json()["must_change_password"]
    body = sign_in(anonymous, "helpdesk.new", PASSWORD)
    assert body["requirements"] == ["password_change"]
    blocked = anonymous.get("/api/v1/devices")
    assert blocked.status_code == 403
    assert blocked.json()["type"] == "urn:netops:problem:password-change-required"

    weak = anonymous.post(
        "/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": "password1234"}
    )
    assert weak.status_code == 422
    assert weak.json()["type"] == "urn:netops:problem:weak-password"
    assert weak.json()["errors"][0]["type"] == "password.common"
    wrong = anonymous.post(
        "/api/v1/auth/password", json={"current_password": "not it at all", "new_password": OTHER}
    )
    assert wrong.status_code == 422
    same = anonymous.post(
        "/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": PASSWORD}
    )
    assert same.status_code == 422
    changed = anonymous.post(
        "/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": OTHER}
    )
    assert changed.status_code == 204
    assert anonymous.get("/api/v1/devices").status_code == 200
    assert login(new_client(anonymous), "helpdesk.new", OTHER).status_code == 200
    assert audit_entries("auth.password.change", outcome="success")
    assert audit_entries("auth.password.change", outcome="failed")


# --- user administration --------------------------------------------------------------------


def test_user_administration(api_client: TestClient, anonymous: TestClient) -> None:
    created = api_client.post(
        "/api/v1/users",
        json={
            "username": "op.admin",
            "display_name": "Op",
            "role": "operator",
            "password": PASSWORD,
        },
    )
    user_id = created.json()["id"]
    assert (
        api_client.post(
            "/api/v1/users",
            json={
                "username": "OP.ADMIN",
                "display_name": "x",
                "role": "viewer",
                "password": PASSWORD,
            },
        ).status_code
        == 409
    )
    weak = api_client.post(
        "/api/v1/users",
        json={"username": "op.weak", "display_name": "x", "role": "viewer", "password": "short"},
    )
    assert weak.status_code == 422
    assert weak.json()["type"] == "urn:netops:problem:weak-password"
    assert api_client.get("/api/v1/users", params={"q": "op.admin"}).json()["total"] == 1

    promoted = api_client.patch(f"/api/v1/users/{user_id}", json={"role": "admin"})
    assert promoted.json()["role"] == "admin"
    (update_entry,) = audit_entries("user.update", target_id=user_id)
    assert update_entry.details == {"fields": ["role"], "old_role": "operator", "new_role": "admin"}

    # The last active admin cannot remove itself; with two admins it can be demoted.
    me = api_client.get("/api/v1/auth/me").json()
    assert api_client.patch(f"/api/v1/users/{user_id}", json={"role": "viewer"}).status_code == 200
    assert api_client.post(f"/api/v1/users/{me['id']}/deactivate").status_code == 409
    assert api_client.patch(f"/api/v1/users/{me['id']}", json={"role": "viewer"}).status_code == 409

    sign_in(anonymous, "op.admin", PASSWORD)
    assert anonymous.get("/api/v1/devices").status_code == 403  # temporary password first
    anonymous.post(
        "/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": OTHER}
    )
    assert anonymous.get("/api/v1/devices").status_code == 200
    # A role change takes effect at once, not when the token expires.
    assert anonymous.get("/api/v1/users").status_code == 403
    deactivated = api_client.post(f"/api/v1/users/{user_id}/deactivate")
    assert deactivated.json()["is_active"] is False
    assert anonymous.get("/api/v1/devices").status_code == 401
    assert login(new_client(anonymous), "op.admin", OTHER).status_code == 401
    assert audit_entries("user.deactivate", target_id=user_id)

    temporary = "temporary pass phrase " + uuid.uuid4().hex[:6]
    reset = api_client.post(
        f"/api/v1/users/{user_id}/reset-password", json={"temporary_password": temporary}
    )
    assert reset.status_code == 204
    api_client.patch(f"/api/v1/users/{user_id}", json={"is_active": True})
    body = sign_in(new_client(anonymous), "op.admin", temporary)
    assert body["requirements"] == ["password_change"]
    assert audit_entries("user.password_reset", target_id=user_id)[0].details[
        "temporary_password_set"
    ]
    assert api_client.get(f"/api/v1/users/{uuid.uuid4()}").status_code == 404
    assert audit_entries("user.create", target_id=user_id)[0].details["role"] == "operator"


# --- credential profiles --------------------------------------------------------------------

SECRETS = {
    "password": "ssh-secret-" + uuid.uuid4().hex,
    "enable_secret": "enable-secret-" + uuid.uuid4().hex,
    "auth_key": "auth-key-" + uuid.uuid4().hex,
    "priv_key": "priv-key-" + uuid.uuid4().hex,
    "new_password": "ssh-secret-2-" + uuid.uuid4().hex,
}


def test_credential_secrets_are_write_only(api_client: TestClient, anonymous: TestClient) -> None:
    responses = []
    ssh = api_client.post(
        "/api/v1/credential-profiles",
        json={
            "name": "lab-ssh",
            "kind": "ssh",
            "username": "netops-ro",
            "password": SECRETS["password"],
            "enable_secret": SECRETS["enable_secret"],
        },
    )
    assert ssh.status_code == 201, ssh.text
    snmp = api_client.post(
        "/api/v1/credential-profiles",
        json={
            "name": "lab-snmp",
            "kind": "snmpv3",
            "username": "netops-snmp",
            "auth_protocol": "sha256",
            "auth_key": SECRETS["auth_key"],
            "priv_protocol": "aes128",
            "priv_key": SECRETS["priv_key"],
        },
    )
    assert snmp.status_code == 201, snmp.text
    ssh_id, snmp_id = ssh.json()["id"], snmp.json()["id"]
    responses += [ssh, snmp]
    detail = api_client.get(f"/api/v1/credential-profiles/{ssh_id}")
    assert detail.json()["enable_secret_set"] is True
    assert set(detail.json()) == {
        "id",
        "name",
        "kind",
        "username",
        "enable_secret_set",
        "auth_protocol",
        "priv_protocol",
        "devices",
        "created_at",
        "updated_at",
    }
    updated = api_client.patch(
        f"/api/v1/credential-profiles/{ssh_id}",
        json={"password": SECRETS["new_password"], "clear_enable_secret": True},
    )
    assert updated.json()["enable_secret_set"] is False
    invalid = api_client.post(
        "/api/v1/credential-profiles",
        json={"name": "bad", "kind": "ssh", "username": "x", "auth_key": SECRETS["auth_key"]},
    )
    assert invalid.status_code == 422
    responses += [
        detail,
        updated,
        invalid,
        api_client.get(f"/api/v1/credential-profiles/{snmp_id}"),
        api_client.get("/api/v1/credential-profiles"),
        api_client.get("/api/v1/audit", params={"limit": 500}),
    ]
    for response in responses:
        for name, value in SECRETS.items():
            assert value not in response.text, (name, response.request.url)
    # Secrets are stored, encrypted: the CLI and collectors still read them.

    async def stored(session: AsyncSession) -> tuple[str, bytes]:
        profile = await session.get(m.CredentialProfile, uuid.UUID(ssh_id))
        assert profile is not None
        assert profile.password is not None
        raw = await session.scalar(
            text("SELECT password_encrypted FROM credential_profiles WHERE id = :id"),
            {"id": ssh_id},
        )
        return profile.password.get_secret_value(), bytes(raw)

    plain, encrypted = run(stored)
    assert plain == SECRETS["new_password"]
    assert SECRETS["new_password"].encode() not in encrypted
    actions = [e.action for e in audit_entries() if e.target_id in (ssh_id, snmp_id)]
    assert actions == ["credentials.create", "credentials.create", "credentials.update"]
    assert audit_entries("credentials.update", target_id=ssh_id)[0].details == {
        "profile_name": "lab-ssh",
        "fields": ["password", "enable_secret"],
    }
    assert api_client.delete(f"/api/v1/credential-profiles/{snmp_id}").status_code == 204
    assert audit_entries("credentials.delete", target_id=snmp_id)

    # Operators see names (to pick profiles for discovery), not details.
    user("op.creds")
    sign_in(anonymous, "op.creds", PASSWORD)
    assert anonymous.get("/api/v1/credential-profiles").status_code == 200
    assert anonymous.get(f"/api/v1/credential-profiles/{ssh_id}").status_code == 403


# --- RBAC with real tokens ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "allowed", "forbidden"),
    [
        (
            UserRole.VIEWER,
            ["GET /api/v1/devices", "GET /api/v1/topology", "GET /api/v1/events"],
            [
                "POST /api/v1/discovery/runs",
                "PUT /api/v1/topology/layout",
                "GET /api/v1/users",
                "GET /api/v1/audit",
                "GET /api/v1/credential-profiles",
            ],
        ),
        (
            UserRole.OPERATOR,
            ["GET /api/v1/credential-profiles", "PUT /api/v1/topology/layout"],
            ["GET /api/v1/users", "GET /api/v1/audit", "POST /api/v1/credential-profiles"],
        ),
        (UserRole.ADMIN, ["GET /api/v1/users", "GET /api/v1/audit"], []),
    ],
)
def test_roles_with_real_tokens(
    anonymous: TestClient, role: UserRole, allowed: list[str], forbidden: list[str]
) -> None:
    name = f"rbac.{role.value}"
    user(name, role)
    sign_in(anonymous, name, PASSWORD)
    bodies: dict[str, dict[str, Any]] = {"PUT /api/v1/topology/layout": {"positions": []}}
    for call in allowed:
        method, path = call.split(" ")
        response = anonymous.request(
            method, path, json=bodies.get(call, {}) if method != "GET" else None
        )
        assert response.status_code not in (401, 403), (call, response.text)
    for call in forbidden:
        method, path = call.split(" ")
        response = anonymous.request(method, path, json={} if method != "GET" else None)
        assert response.status_code == 403, (call, response.text)
    denied = [e for e in audit_entries("access.denied") if e.details["role"] == role.value]
    assert len(denied) >= len(forbidden)


# --- the audit log --------------------------------------------------------------------------


def test_audit_endpoint_filters(api_client: TestClient, anonymous: TestClient) -> None:
    login(anonymous, "nobody-at-all", PASSWORD)
    page = api_client.get(
        "/api/v1/audit", params={"action": "auth.*", "outcome": "failed", "limit": 5}
    ).json()
    assert page["items"]
    assert all(i["action"].startswith("auth.") and i["outcome"] == "failed" for i in page["items"])
    mine = api_client.get("/api/v1/audit", params={"actor": ADMIN}).json()
    assert mine["items"]
    assert all(i["actor"]["username"] == ADMIN for i in mine["items"])
    since = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    assert api_client.get("/api/v1/audit", params={"from": since}).json()["total"] == 0


def test_the_audit_log_cannot_be_changed(api_client: TestClient) -> None:
    login(TestClient(api_client.app), "nobody", PASSWORD)
    before = len(audit_entries())
    for sql in (
        "UPDATE audit_log SET outcome = 'success'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ):

        async def attempt(session: AsyncSession, sql: str = sql) -> str:
            try:
                await session.execute(text(sql))
                await session.commit()
            except DBAPIError as exc:
                await session.rollback()
                return str(exc.orig)
            return "allowed"

        message = run(attempt)
        assert "append-only" in message, (sql, message)
    assert len(audit_entries()) == before


def test_discovery_refresh_backup_and_layout_are_audited(
    api: tuple[TestClient, Recorder], profiles: list[uuid.UUID]
) -> None:
    client, _ = api
    response = client.post(
        "/api/v1/discovery/runs",
        json={
            "seeds": ["10.255.0.2"],
            "allowed_subnets": ["10.255.0.0/24"],
            "credential_profile_ids": [str(profiles[1])],
        },
    )
    assert response.status_code == 202, response.text
    assert client.put("/api/v1/topology/layout", json={"positions": []}).status_code == 200

    async def device(session: AsyncSession) -> uuid.UUID:
        row = m.Device(
            id=uuid.uuid4(),
            hostname="audit-sw",
            mgmt_ip="10.255.0.99",
            is_managed=True,
            discovered_via="manual",
        )
        session.add(row)
        await session.commit()
        return row.id

    device_id = run(device)
    refreshed = client.post(f"/api/v1/devices/{device_id}/refresh", json={"kinds": ["config"]})
    assert refreshed.status_code == 202, refreshed.text
    assert audit_entries("discovery.start")[-1].details["seeds"] == ["10.255.0.2"]
    assert audit_entries("topology.layout.save")[-1].target_id == "l2"
    assert audit_entries("device.refresh", target_id=str(device_id))
    assert audit_entries("config.backup", target_id=str(device_id))[0].details["kinds"] == [
        "config"
    ]


def test_no_password_or_secret_ends_up_in_the_audit_log(app_on_test_database: None) -> None:
    for entry in audit_entries():
        flattened = json.dumps(entry.details)
        assert PASSWORD not in flattened
        assert OTHER not in flattened
        assert not any(value in flattened for value in SECRETS.values())
