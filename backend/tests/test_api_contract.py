"""The v1 API contract: routes, problem details, security, examples, committed document."""

import importlib
import inspect
import pkgutil
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from pydantic import BaseModel, TypeAdapter

import netops.api.schemas
from netops.api.app import build_api
from netops.api.export_openapi import render
from netops.api.problems import NOT_IMPLEMENTED, PROBLEM_MEDIA_TYPE, VALIDATION_ERROR
from netops.api.schemas.hosts import FOUND_EXAMPLE, NOT_FOUND_EXAMPLE, HostLocateResult

OPENAPI_JSON = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"

# The endpoint list of the step-4 specification. A route added or removed without updating
# this list (and the contract review that goes with it) fails the tests.
EXPECTED_V1_OPERATIONS = {
    ("POST", "/api/v1/auth/login"),
    ("GET", "/api/v1/auth/me"),
    ("GET", "/api/v1/locations"),
    ("POST", "/api/v1/locations"),
    ("GET", "/api/v1/locations/{location_id}"),
    ("PATCH", "/api/v1/locations/{location_id}"),
    ("DELETE", "/api/v1/locations/{location_id}"),
    ("GET", "/api/v1/devices"),
    ("GET", "/api/v1/devices/{device_id}"),
    ("POST", "/api/v1/devices/{device_id}/refresh"),
    ("GET", "/api/v1/devices/{device_id}/interfaces"),
    ("GET", "/api/v1/interfaces/{interface_id}"),
    ("POST", "/api/v1/discovery/runs"),
    ("GET", "/api/v1/discovery/runs"),
    ("GET", "/api/v1/discovery/runs/{run_id}"),
    ("GET", "/api/v1/topology"),
    ("GET", "/api/v1/topology/changes"),
    ("GET", "/api/v1/hosts/locate"),
    ("POST", "/api/v1/diagnosis/path-trace"),
    ("GET", "/api/v1/diagnosis/impact"),
    ("GET", "/api/v1/alarms"),
    ("GET", "/api/v1/alarms/{alarm_id}"),
    ("POST", "/api/v1/alarms/{alarm_id}/acknowledge"),
    ("GET", "/api/v1/incidents"),
    ("GET", "/api/v1/incidents/{incident_id}"),
    ("GET", "/api/v1/findings"),
    ("GET", "/api/v1/metrics"),
    ("GET", "/api/v1/events"),
    ("GET", "/api/v1/devices/{device_id}/configs"),
    ("GET", "/api/v1/configs/diff"),
    ("GET", "/api/v1/configs/{version_id}"),
    ("GET", "/api/v1/config-changes"),
    ("GET", "/api/v1/jobs/{job_id}"),
}
PUBLIC_OPERATIONS = {("GET", "/api/health"), ("POST", "/api/v1/auth/login")}

SOME_ID = "5e0c7a1d-0000-4000-8000-000000002004"
OTHER_ID = "5e0c7a1d-0000-4000-8000-000000006001"
# Required query parameters, so that requests pass validation and reach the stub.
REQUIRED_QUERY: dict[str, dict[str, str]] = {
    "/api/v1/topology/changes": {"since": "2026-10-08T00:00:00Z"},
    "/api/v1/hosts/locate": {"query": "10.0.20.57"},
    "/api/v1/metrics": {"device_id": SOME_ID, "name": "cpu_5min"},
    "/api/v1/configs/diff": {"from": SOME_ID, "to": OTHER_ID},
}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return build_api().openapi()


def _operations(spec: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (method.upper(), path): operation
        for path, item in spec["paths"].items()
        for method, operation in item.items()
    }


def test_v1_routes_match_the_contract(spec: dict[str, Any]) -> None:
    v1 = {key for key in _operations(spec) if key[1].startswith("/api/v1/")}
    assert v1 == EXPECTED_V1_OPERATIONS


@pytest.mark.parametrize(("method", "path"), sorted(EXPECTED_V1_OPERATIONS))
def test_every_v1_route_is_a_501_stub(
    client: TestClient, spec: dict[str, Any], method: str, path: str
) -> None:
    operation = _operations(spec)[(method, path)]
    body = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
    url = re.sub(r"\{[^}]+\}", SOME_ID, path)

    response = client.request(
        method, url, params=REQUIRED_QUERY.get(path), json=body.get("example")
    )

    assert response.status_code == 501, response.text
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json() == {
        "type": NOT_IMPLEMENTED,
        "title": "Not Implemented",
        "status": 501,
        "detail": "This endpoint is part of the API contract but is not implemented yet.",
        "instance": url,
    }


def test_validation_errors_are_problem_details(client: TestClient) -> None:
    response = client.get("/api/v1/devices", params={"limit": 0})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    problem = response.json()
    assert problem["type"] == VALIDATION_ERROR
    assert problem["errors"][0]["loc"] == ["query", "limit"]


def test_time_travel_requires_a_timezone(client: TestClient) -> None:
    response = client.get(f"/api/v1/interfaces/{SOME_ID}", params={"at": "2026-10-01T10:00:00"})
    assert response.status_code == 422


def test_unknown_routes_are_problem_details(client: TestClient) -> None:
    response = client.get("/api/v1/no-such-thing")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json()["title"] == "Not Found"


def test_openapi_document_is_valid(spec: dict[str, Any]) -> None:
    validate(spec)


def test_security_is_required_everywhere_except_health_and_login(spec: dict[str, Any]) -> None:
    assert spec["components"]["securitySchemes"]["bearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": spec["components"]["securitySchemes"]["bearerAuth"]["description"],
    }
    for key, operation in _operations(spec).items():
        if key in PUBLIC_OPERATIONS:
            assert "security" not in operation, key
        else:
            assert operation.get("security") == [{"bearerAuth": []}], key


def test_every_schema_has_an_example(spec: dict[str, Any]) -> None:
    # Enum schemas are exempt: their allowed values are the example.
    missing = [
        name
        for name, schema in spec["components"]["schemas"].items()
        if "enum" not in schema and not schema.get("examples")
    ]
    assert missing == []


def test_every_json_response_has_an_example(spec: dict[str, Any]) -> None:
    missing = [
        (key, status, media_type)
        for key, operation in _operations(spec).items()
        for status, response in operation["responses"].items()
        for media_type, media in response.get("content", {}).items()
        if "example" not in media and "examples" not in media
    ]
    assert missing == []


def _api_models() -> list[type[BaseModel]]:
    models = []
    for module_info in pkgutil.iter_modules(netops.api.schemas.__path__):
        module = importlib.import_module(f"netops.api.schemas.{module_info.name}")
        models += [
            cls
            for cls in vars(module).values()
            if inspect.isclass(cls)
            and issubclass(cls, BaseModel)
            and cls.__module__ == module.__name__
            and "examples" in (cls.model_config.get("json_schema_extra") or {})
        ]
    return models


@pytest.mark.parametrize("model", _api_models(), ids=lambda model: model.__name__)
def test_examples_are_valid_instances(model: type[BaseModel]) -> None:
    extra = model.model_config.get("json_schema_extra")
    assert isinstance(extra, dict)
    for example in extra["examples"]:
        model.model_validate(example)


def test_host_locate_examples_are_valid() -> None:
    adapter: TypeAdapter[Any] = TypeAdapter(HostLocateResult)
    assert adapter.validate_python(FOUND_EXAMPLE).status == "found"
    assert adapter.validate_python(NOT_FOUND_EXAMPLE).status == "not_found"


def test_committed_openapi_document_is_up_to_date() -> None:
    assert OPENAPI_JSON.read_text(encoding="utf-8") == render(), (
        "docs/api/openapi.json is out of date: run `make openapi` and commit the result"
    )
