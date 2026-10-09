"""RFC 9457 problem details: the one error format of the API (``application/problem+json``)."""

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"

# Problem types specific to this API. Plain HTTP errors use "about:blank" (RFC 9457 4.2.1).
NOT_IMPLEMENTED = "urn:netops:problem:not-implemented"
VALIDATION_ERROR = "urn:netops:problem:validation-error"


VALIDATION_ISSUE_EXAMPLE: dict[str, Any] = {
    "loc": ["query", "limit"],
    "msg": "Input should be less than or equal to 500",
    "type": "less_than_equal",
}


class ValidationIssue(BaseModel):
    """One invalid input (extension member ``errors`` of a validation problem)."""

    model_config = ConfigDict(json_schema_extra={"examples": [VALIDATION_ISSUE_EXAMPLE]})

    loc: list[str | int]
    msg: str
    type: str


class Problem(BaseModel):
    """RFC 9457 problem details, returned with every 4xx/5xx response."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": "about:blank",
                    "title": "Not Found",
                    "status": 404,
                    "detail": "Device 5e0c7a1d-0000-4000-8000-000000002004 does not exist.",
                    "instance": "/api/v1/devices/5e0c7a1d-0000-4000-8000-000000002004",
                }
            ]
        }
    )

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    # Extension member, present on validation problems only.
    errors: list[ValidationIssue] | None = None


class ProblemError(Exception):
    """Raise to answer with a problem details response."""

    def __init__(
        self, status: int, *, detail: str | None = None, type_: str = "about:blank"
    ) -> None:
        super().__init__(detail or HTTPStatus(status).phrase)
        self.status = status
        self.detail = detail
        self.type = type_


def not_implemented() -> ProblemError:
    """The error every contract stub raises until its module implements it."""
    return ProblemError(
        HTTPStatus.NOT_IMPLEMENTED,
        detail="This endpoint is part of the API contract but is not implemented yet.",
        type_=NOT_IMPLEMENTED,
    )


def problem_response(
    request: Request,
    status: int,
    *,
    detail: str | None = None,
    type_: str = "about:blank",
    errors: list[ValidationIssue] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    problem = Problem(
        type=type_,
        title=HTTPStatus(status).phrase,
        status=status,
        detail=detail,
        instance=request.url.path,
        errors=errors,
    )
    return JSONResponse(
        problem.model_dump(exclude_none=True),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


# Starlette types handlers as (Request, Exception); each is only registered for its own type.
async def _problem_error(request: Request, exc: Exception) -> JSONResponse:
    error = cast("ProblemError", exc)
    return problem_response(request, error.status, detail=error.detail, type_=error.type)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    error = cast("StarletteHTTPException", exc)
    phrase = HTTPStatus(error.status_code).phrase
    detail = error.detail if isinstance(error.detail, str) and error.detail != phrase else None
    return problem_response(request, error.status_code, detail=detail, headers=error.headers)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    errors = [
        ValidationIssue(loc=list(error["loc"]), msg=error["msg"], type=error["type"])
        for error in cast("RequestValidationError", exc).errors()
    ]
    return problem_response(
        request,
        HTTPStatus.UNPROCESSABLE_ENTITY,
        detail="The request is invalid; see errors.",
        type_=VALIDATION_ERROR,
        errors=errors,
    )


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error", extra={"path": request.url.path})
    return problem_response(request, HTTPStatus.INTERNAL_SERVER_ERROR)


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemError, _problem_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)


_DESCRIPTIONS = {
    400: "Bad request",
    401: "Missing or invalid bearer token",
    404: "The resource does not exist",
    409: "Conflicts with the current state of the resource",
    422: "Validation error (see the `errors` member)",
    501: "Part of the contract, not implemented yet",
}


def problems(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses`` entries for problem details with the given status codes."""
    return {status: {"model": Problem, "description": _DESCRIPTIONS[status]} for status in statuses}
