"""The FastAPI application object and its OpenAPI document (the API contract)."""

from collections.abc import Iterator
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

from netops import __version__
from netops.api.problems import (
    NOT_IMPLEMENTED,
    PROBLEM_MEDIA_TYPE,
    VALIDATION_ERROR,
    VALIDATION_ISSUE_EXAMPLE,
    install_problem_handlers,
)
from netops.api.router import api_router

DESCRIPTION = """\
REST API of the NetOps platform. Conventions (versioning, errors, pagination, time travel
with `at`, jobs, security) are described in `docs/adr/0003-api-conventions.md`; live updates
over WebSocket in `docs/api/websocket.md`.

Endpoints that return **501 Not Implemented** are part of the contract but not built yet.
"""

TAGS: list[dict[str, Any]] = [
    {"name": "health", "description": "Liveness of the API and its dependencies."},
    {"name": "auth", "description": "Login and the current user (M7; contract only)."},
    {"name": "locations", "description": "Campus, building and floor hierarchy (M2)."},
    {"name": "devices", "description": "Inventory: devices and interfaces (M1/M2)."},
    {"name": "discovery", "description": "CDP/LLDP discovery runs (M1)."},
    {"name": "topology", "description": "L2/L3 topology graph and drift (M1)."},
    {"name": "hosts", "description": "Locate a host by IP or MAC address (M6)."},
    {"name": "diagnosis", "description": "Path trace and impact analysis (M6)."},
    {"name": "alarms", "description": "Alarm lifecycle (M3)."},
    {"name": "incidents", "description": "Alarms grouped by root cause (M3/M6)."},
    {"name": "findings", "description": "Root-cause candidates with evidence (M6)."},
    {"name": "metrics", "description": "Time-series metrics (M3)."},
    {"name": "events", "description": "Received syslog messages and SNMP traps (M3)."},
    {"name": "configs", "description": "Configuration versions, diffs and changes (M4)."},
    {"name": "jobs", "description": "Status of long-running operations."},
]

_SCHEMA_PREFIX = "#/components/schemas/"

_PROBLEM_DETAILS = {
    401: "A valid bearer token is required.",
    404: "The requested resource does not exist.",
    409: "The request conflicts with the current state of the resource.",
    422: "The request is invalid; see errors.",
    501: "This endpoint is part of the API contract but is not implemented yet.",
}


def _operations(schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for path_item in schema.get("paths", {}).values():
        yield from path_item.values()


def _component_ref(media_schema: dict[str, Any]) -> str | None:
    """Component name a media type's schema points to (also through ``X | None``)."""
    ref = media_schema.get("$ref")
    if ref is None:
        refs = [s["$ref"] for s in media_schema.get("anyOf", []) if "$ref" in s]
        ref = refs[0] if len(refs) == 1 else None
    return ref.removeprefix(_SCHEMA_PREFIX) if isinstance(ref, str) else None


def _contents(operation: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield operation.get("requestBody", {}).get("content", {})
    for response in operation.get("responses", {}).values():
        yield response.get("content", {})


def _problem_example(status: int) -> dict[str, Any]:
    example: dict[str, Any] = {"type": "about:blank", "title": HTTPStatus(status).phrase}
    if status == HTTPStatus.NOT_IMPLEMENTED:
        example["type"] = NOT_IMPLEMENTED
    if status == HTTPStatus.UNPROCESSABLE_ENTITY:
        example["type"] = VALIDATION_ERROR
        example["errors"] = [VALIDATION_ISSUE_EXAMPLE]
    return example | {"status": status, "detail": _PROBLEM_DETAILS.get(status)}


def _use_problem_media_type(schema: dict[str, Any]) -> None:
    """Problem details are served as application/problem+json (RFC 9457), each response
    with an example matching its status code."""
    for operation in _operations(schema):
        for status, response in operation.get("responses", {}).items():
            content = response.get("content", {})
            media = content.get("application/json")
            if media is not None and _component_ref(media.get("schema", {})) == "Problem":
                media["example"] = _problem_example(int(status))
                content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")


def _add_media_type_examples(schema: dict[str, Any]) -> None:
    """Copy each schema's first example to the media types using it.

    The examples are defined once, on the Pydantic models; mock servers such as Prism
    read them from the media type.
    """
    components = schema.get("components", {}).get("schemas", {})
    for operation in _operations(schema):
        for content in _contents(operation):
            for media in content.values():
                if "example" in media or "examples" in media:
                    continue
                name = _component_ref(media.get("schema", {}))
                examples = components.get(name, {}).get("examples") if name else None
                if examples:
                    media["example"] = examples[0]


class NetOpsAPI(FastAPI):
    def openapi(self) -> dict[str, Any]:
        if self.openapi_schema is None:
            schema = super().openapi()
            _use_problem_media_type(schema)
            _add_media_type_examples(schema)
            self.openapi_schema = schema
        return self.openapi_schema


def _operation_id(route: APIRoute) -> str:
    # Handler names are unique, short and readable in generated clients ("list_devices").
    return route.name


def build_api(**kwargs: Any) -> NetOpsAPI:
    """The application without process setup (logging, lifespan): routes and contract only."""
    app = NetOpsAPI(
        title="NetOps Platform API",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        generate_unique_id_function=_operation_id,
        **kwargs,
    )
    install_problem_handlers(app)
    app.include_router(api_router, prefix="/api")
    return app
