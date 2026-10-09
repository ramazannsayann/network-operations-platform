"""Structured logging: one JSON object per line on stdout, so container logs are machine-readable.

Use the standard library API and pass structured fields through ``extra``::

    logger = logging.getLogger(__name__)
    logger.info("device polled", extra={"device": "core-sw-1", "duration_ms": 412})
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, Literal

# Attributes every LogRecord has; anything else on a record came from ``extra``.
# "color_message" is uvicorn's ANSI-coloured duplicate of the message.
_RESERVED_ATTRS = frozenset(
    vars(logging.LogRecord("", logging.INFO, "", 0, "", None, None)).keys()
    | {"message", "asctime", "color_message"}
)

# Third-party loggers that install their own handlers; we route them through ours instead.
_CAPTURED_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "celery")


class JsonFormatter(logging.Formatter):
    """Render a log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(
            {key: value for key, value in vars(record).items() if key not in _RESERVED_ATTRS}
        )
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", fmt: Literal["json", "console"] = "json") -> None:
    """Install a single stdout handler on the root logger. Safe to call more than once."""
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    for name in _CAPTURED_LOGGERS:
        captured = logging.getLogger(name)
        captured.handlers.clear()
        captured.propagate = True
