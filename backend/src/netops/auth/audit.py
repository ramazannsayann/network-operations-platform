"""Writing the audit log (table ``audit_log``, append-only in the database).

``record`` adds an entry to the caller's session, so it commits (or rolls back) together
with the action it describes. ``record_now`` commits an entry of its own at once, for
outcomes whose request will not commit anything: failed logins, denied requests.

Entries never hold secrets: ``details`` refuses keys that name one (password, secret,
token, code, key), and callers pass names and ids only.
"""

import logging
import uuid
from collections.abc import Mapping
from ipaddress import ip_address
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from netops.db.enums import AuditOutcome
from netops.db.models import AuditLogEntry
from netops.db.session import get_sessionmaker

logger = logging.getLogger(__name__)

_SECRET_WORDS = ("password", "secret", "token", "code", "key")


class AuditDetailsError(ValueError):
    """``details`` would store something that looks like a secret."""


def _checked(details: Mapping[str, Any] | None) -> dict[str, Any]:
    def walk(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                lowered = str(key).lower()
                if any(word in lowered for word in _SECRET_WORDS) and not lowered.endswith(
                    ("_count", "_left", "_set", "_changed", "_name", "_id", "_kind")
                ):
                    raise AuditDetailsError(f"audit details must not hold {path}{key}")
                walk(item, f"{path}{key}.")
        elif isinstance(value, list | tuple):
            for item in value:
                walk(item, path)

    data = dict(details or {})
    walk(data, "")
    return data


def host(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        return str(ip_address(ip))
    except ValueError:
        return None


def entry(
    action: str,
    outcome: AuditOutcome,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_ip: str | None = None,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    details: Mapping[str, Any] | None = None,
) -> AuditLogEntry:
    return AuditLogEntry(
        action=action,
        outcome=outcome,
        actor_user_id=actor_user_id,
        actor_ip=host(actor_ip),
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=_checked(details),
    )


def record(session: AsyncSession, action: str, outcome: AuditOutcome, **values: Any) -> None:
    """Add an entry to ``session``; it is written when the caller commits."""
    session.add(entry(action, outcome, **values))


async def record_now(action: str, outcome: AuditOutcome, **values: Any) -> None:
    """Write an entry in a transaction of its own. Never raises: a failing audit write is
    logged (without the details) and the request goes on."""
    row = entry(action, outcome, **values)
    try:
        async with get_sessionmaker()() as session:
            session.add(row)
            await session.commit()
    except Exception:
        logger.exception("writing an audit entry failed", extra={"action": action})
