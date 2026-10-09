"""Parameters and responses shared by the v1 endpoints (conventions in ADR-0003)."""

from typing import Annotated, Any

from fastapi import Depends, Query, status
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession

from netops.db.session import get_session

DEFAULT_LIMIT = 50
MAX_LIMIT = 500

Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT, description=f"Page size (1-{MAX_LIMIT}).")]
Offset = Annotated[int, Query(ge=0, description="Number of items to skip.")]
At = Annotated[
    AwareDatetime | None,
    Query(
        description="Read observed network state as of this time (ISO 8601 with offset). "
        "Defaults to now. Uses the latest successful collection run started at or before it."
    ),
]
From = Annotated[
    AwareDatetime | None,
    Query(alias="from", description="Start of the time range, inclusive (ISO 8601)."),
]
To = Annotated[
    AwareDatetime | None,
    Query(description="End of the time range, exclusive (ISO 8601). Defaults to now."),
]
SearchText = Annotated[
    str | None, Query(min_length=1, max_length=200, description="Case-insensitive text search.")
]

# OpenAPI entry for 202 Accepted: the body is a JobRef, Location points at the job.
ACCEPTED: dict[int | str, dict[str, Any]] = {
    status.HTTP_202_ACCEPTED: {
        "description": "Accepted: the work runs as a job.",
        "headers": {"Location": {"description": "URL of the job.", "schema": {"type": "string"}}},
    }
}


# --- Dependencies of implemented endpoints --------------------------------------------------

Session = Annotated[AsyncSession, Depends(get_session)]


class TaskQueue:
    """Hands work to the Celery workers (by task name, so the API does not import task code).

    A dependency so that API tests can record the calls instead of needing a broker.
    """

    def __call__(self, task: str, *args: Any) -> None:
        from netops.workers.celery_app import celery_app

        celery_app.send_task(task, args=list(args))


def get_task_queue() -> TaskQueue:
    return TaskQueue()


Enqueue = Annotated[TaskQueue, Depends(get_task_queue)]
