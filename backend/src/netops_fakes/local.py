"""A whole fake topology on 127.0.0.1, for integration tests and scale runs.

Each served device listens on its own random port; ``resolve`` is the connection-target
resolver (netops.netaccess.target) that sends a session for a device's management address
(or its second management SVI) to that port. Addresses no fake device owns resolve to a
closed port, so a session to them fails as unreachable instead of leaving the machine.
``connections`` records every address a session was opened for, so tests can prove that
discovery never tried an address (e.g. one outside the allowed subnets).
"""

import threading
from types import TracebackType
from typing import Self

from netops_fakes.device import FakeCiscoDevice, FakeFleet, lab_devices
from netops_fakes.lab import Lab, build
from netops_fakes.topology import Topology

_CLOSED_PORT = 9  # discard; nothing listens there on a test machine


class LocalLab:
    def __init__(self, topology: Topology, username: str, password: str) -> None:
        self.lab: Lab = build(topology)
        self.devices: dict[str, FakeCiscoDevice] = lab_devices(self.lab, username, password)
        self.fleet = FakeFleet(self.devices.values())
        self.targets: dict[str, int] = {}
        self.connections: list[str] = []
        self._lock = threading.Lock()

    def start(self) -> Self:
        self.fleet.start()
        for state in self.lab.served():
            port = self.devices[state.name].port
            device = state.device
            for address in (device.mgmt_ip, *(svi.ip for svi in device.extra_svis)):
                self.targets[str(address)] = port
        return self

    def stop(self) -> None:
        self.fleet.stop()

    def resolve(self, host: str, port: int) -> tuple[str, int]:
        with self._lock:
            self.connections.append(host)
        return "127.0.0.1", self.targets.get(host, _CLOSED_PORT)

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
