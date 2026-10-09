"""Celery tasks, executed eagerly in-process (no broker or worker involved)."""

from netops.workers.tasks import ping


def test_ping_task_returns_pong() -> None:
    assert ping.apply().get() == "pong"
