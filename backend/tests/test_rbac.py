"""Authorization: every route declares a permission, and every role gets exactly what the
mapping in netops.auth.rbac grants (no database: the principal is a dependency override).
"""

import re
from collections.abc import AsyncIterator, Iterator
from http import HTTPStatus
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from netops.api.app import build_api
from netops.api.problems import (
    FORBIDDEN,
    MFA_ENROLLMENT_REQUIRED,
    PASSWORD_CHANGE_REQUIRED,
    ProblemError,
)
from netops.api.security import PERMISSION_EXTENSION, RequirePermission, get_principal
from netops.auth.rbac import ROLE_PERMISSIONS, Permission
from netops.db.enums import UserRole
from netops.db.session import get_session
from tests.conftest import principal
from tests.test_api_contract import OTHER_ID, PUBLIC_OPERATIONS, REQUIRED_QUERY, SOME_ID

# Without a permission on purpose: they are how a client gets a token, or the health check.
PUBLIC_ROUTES = {(method, path) for method, path in PUBLIC_OPERATIONS}


def api_routes(app: FastAPI) -> Iterator[tuple[str, str, APIRoute]]:
    """(method, full path, route) of every API route, also inside included routers."""
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                yield method, route.path, route
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is None:
            continue
        for context in contexts():
            original = context.original_route
            if isinstance(original, APIRoute):
                for method in original.methods:
                    yield method, context.path, original


def guards(dependant: Dependant) -> list[RequirePermission]:
    found = []
    for dependency in dependant.dependencies:
        if isinstance(dependency.call, RequirePermission):
            found.append(dependency.call)
        found.extend(guards(dependency))
    return found


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return build_api()


@pytest.fixture(scope="module")
def spec(app: FastAPI) -> dict[str, Any]:
    return app.openapi()


def test_the_route_table_has_every_contract_operation(app: FastAPI, spec: dict[str, Any]) -> None:
    routes = {(method, path) for method, path, _ in api_routes(app) if path.startswith("/api/")}
    operations = {(method.upper(), path) for path, item in spec["paths"].items() for method in item}
    assert routes == operations
    assert len(routes) > 50


def test_every_route_declares_exactly_one_permission(app: FastAPI, spec: dict[str, Any]) -> None:
    unguarded, mismatched = [], []
    for method, path, route in api_routes(app):
        if not path.startswith("/api/"):
            continue
        found = guards(route.dependant)
        declared = spec["paths"][path][method.lower()].get(PERMISSION_EXTENSION)
        if (method, path) in PUBLIC_ROUTES:
            assert not found, (method, path)
            assert declared is None, (method, path)
            continue
        if len(found) != 1:
            unguarded.append((method, path, found))
        elif found[0].permission.value != declared:
            mismatched.append((method, path, found[0].permission, declared))
    assert unguarded == []
    assert mismatched == []


def test_every_permission_is_used_and_granted_to_admin(spec: dict[str, Any]) -> None:
    used = {
        operation[PERMISSION_EXTENSION]
        for item in spec["paths"].values()
        for operation in item.values()
        if PERMISSION_EXTENSION in operation
    }
    # configs:backup guards config collection inside POST /devices/{id}/refresh.
    assert used | {Permission.CONFIGS_BACKUP.value} == {p.value for p in Permission}
    assert ROLE_PERMISSIONS[UserRole.ADMIN] == frozenset(Permission)


def test_roles_are_nested_and_viewers_only_read() -> None:
    viewer, operator = ROLE_PERMISSIONS[UserRole.VIEWER], ROLE_PERMISSIONS[UserRole.OPERATOR]
    assert viewer < operator < ROLE_PERMISSIONS[UserRole.ADMIN]
    assert all(p.value.endswith(":read") or p is Permission.PROFILE for p in viewer), (
        "viewer may only read"
    )
    admin_only = {
        Permission.USERS_MANAGE,
        Permission.CREDENTIALS_MANAGE,
        Permission.AUDIT_READ,
        Permission.LOCATIONS_MANAGE,
    }
    assert not admin_only & operator


def _operations(spec: dict[str, Any]) -> list[tuple[str, str, str, dict[str, Any]]]:
    return sorted(
        (method.upper(), path, operation[PERMISSION_EXTENSION], operation)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if PERMISSION_EXTENSION in operation
    )


def _request(client: TestClient, method: str, path: str, operation: dict[str, Any]) -> Any:
    body = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
    url = re.sub(r"\{[^}]+\}", SOME_ID, path)
    params = REQUIRED_QUERY.get(path, {"from": SOME_ID, "to": OTHER_ID} if "diff" in path else {})
    return client.request(method, url, params=params, json=body.get("example"))


class Denials:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, action: str, outcome: Any, **values: Any) -> None:
        self.calls.append({"action": action, "outcome": outcome.value, **values})


@pytest.fixture
def denials(monkeypatch: pytest.MonkeyPatch) -> Denials:
    """Denied requests are audited in a transaction of their own; captured here."""
    recorder = Denials()
    monkeypatch.setattr("netops.api.security.audit.record_now", recorder)
    return recorder


async def no_database() -> AsyncIterator[Any]:
    raise ProblemError(HTTPStatus.SERVICE_UNAVAILABLE, detail="No database in unit tests.")
    yield  # pragma: no cover - makes this a generator dependency like get_session


def client_as(role: str, requirements: tuple[str, ...] = ()) -> TestClient:
    app = build_api()
    app.dependency_overrides[get_principal] = lambda: principal(role, requirements)
    # Unit tests have no database: allowed requests stop with 503 where a handler would
    # open a session. Any answer but 401/403 shows the permission check let them through;
    # denied ones must get their 403 before any dependency touches the database.
    app.dependency_overrides[get_session] = no_database
    return TestClient(app)


MATRIX = [
    (role, method, path, permission)
    for role in UserRole
    for method, path, permission, _ in _operations(build_api().openapi())
]


@pytest.mark.parametrize(("role", "method", "path", "permission"), MATRIX)
def test_role_matrix(
    spec: dict[str, Any], denials: Denials, role: UserRole, method: str, path: str, permission: str
) -> None:
    operation = spec["paths"][path][method.lower()]
    response = _request(client_as(role.value), method, path, operation)
    if Permission(permission) in ROLE_PERMISSIONS[role]:
        assert response.status_code not in (401, 403), response.text
        assert denials.calls == []
    else:
        assert response.status_code == 403, response.text
        problem = response.json()
        assert problem["type"] == FORBIDDEN
        assert permission in problem["detail"]
        (call,) = denials.calls
        assert call["action"] == "access.denied"
        assert call["outcome"] == "denied"
        assert call["target_id"] == f"{method} {path}"
        assert call["details"]["permission"] == permission


@pytest.mark.parametrize(
    ("requirement", "problem_type"),
    [("mfa_enrollment", MFA_ENROLLMENT_REQUIRED), ("password_change", PASSWORD_CHANGE_REQUIRED)],
)
def test_a_session_with_requirements_only_reaches_its_own_account(
    spec: dict[str, Any], denials: Denials, requirement: str, problem_type: str
) -> None:
    client = client_as("admin", (requirement,))
    for method, path, permission, operation in _operations(spec):
        response = _request(client, method, path, operation)
        if permission == Permission.PROFILE.value:
            assert response.status_code not in (401, 403), (path, response.text)
        else:
            assert response.status_code == 403, (path, response.text)
            assert response.json()["type"] == problem_type
    assert {call["details"]["reason"] for call in denials.calls} == {requirement}


def test_requests_without_a_valid_token_get_401(
    anonymous_client: TestClient, spec: dict[str, Any]
) -> None:
    for method, path, _, operation in _operations(spec):
        for headers in ({}, {"Authorization": "Bearer not-a-jwt"}, {"Authorization": "Basic x"}):
            body = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
            url = re.sub(r"\{[^}]+\}", SOME_ID, path)
            response = anonymous_client.request(
                method,
                url,
                params=REQUIRED_QUERY.get(path),
                json=body.get("example"),
                headers=headers,
            )
            assert response.status_code == 401, (method, path, headers, response.text)
            assert response.headers["www-authenticate"] == "Bearer"
