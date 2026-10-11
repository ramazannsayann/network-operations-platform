"""Discovery at scale: a generated campus (netops_fakes.topology.synthetic) on 127.0.0.1.

CI runs it with 50 devices (``make test-scale``); for a manual run with more, set
SCALE_DEVICES (6-240), e.g. ``make test-scale SCALE_DEVICES=200``. The duration is
printed, along with the accuracy report.
"""

import asyncio
import ipaddress
import os
import time
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from netops.core.settings import get_settings
from netops.db.enums import JobStatus
from netops.discovery.engine import run_discovery
from netops.discovery.service import request_discovery
from netops_fakes.accuracy import evaluate
from netops_fakes.local import LocalLab
from netops_fakes.topology import synthetic
from tests.integration.support import PASSWORD, USERNAME, run

pytestmark = [pytest.mark.integration, pytest.mark.scale]

DEVICES = int(os.environ.get("SCALE_DEVICES", "50"))


def test_discover_a_generated_campus(
    profiles: list[uuid.UUID], capsys: pytest.CaptureFixture[str]
) -> None:
    topology = synthetic(DEVICES)
    seed = ipaddress.ip_address("10.255.0.2")  # core1
    allowed = ipaddress.ip_network(topology.management_subnet)

    async def request(session: AsyncSession) -> uuid.UUID:
        discovery_run, _ = await request_discovery(session, [seed], [allowed], [profiles[1]])
        return discovery_run.id

    with LocalLab(topology, USERNAME, PASSWORD) as lab:
        run_id = run(request)
        started = time.perf_counter()
        status = asyncio.run(run_discovery(run_id, get_settings(), lab.resolve))
        duration = time.perf_counter() - started
    assert status is JobStatus.SUCCEEDED

    accuracy = run(lambda session: evaluate(session, topology))
    with capsys.disabled():
        print(  # noqa: T201
            f"\n\nDiscovery of a generated campus: {DEVICES} devices, "
            f"{len(topology.links)} links, SSH_MAX_CONCURRENCY="
            f"{get_settings().ssh_max_concurrency}: {duration:.1f} s\n{accuracy.report()}\n"
        )
    assert accuracy.perfect
    assert accuracy.roles.matched == accuracy.roles.expected
