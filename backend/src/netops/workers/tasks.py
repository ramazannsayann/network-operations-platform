"""Celery tasks."""

from netops.workers.celery_app import celery_app


@celery_app.task(name="netops.ping")
def ping() -> str:
    """Smoke-test task: proves the broker, a worker and the result backend are wired up."""
    return "pong"
