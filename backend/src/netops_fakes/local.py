"""A whole fake topology on 127.0.0.1, for integration tests and scale runs.

Each served device listens on its own random port; ``resolve`` is the connection-target
resolver (netops.netaccess.target) that sends a session for a device's management address
(or its second management SVI) to that port. Addresses no fake device owns resolve to a
closed port, so a session to them fails as unreachable instead of leaving the machine.
``connections`` records every address a session was opened for, so tests can prove that
discovery never tried an address (e.g. one outside the allowed subnets).

Changes (netops_fakes.scenarios) apply in memory (``apply``); ``send_syslog`` sends a
device's syslog from a UDP socket of its own, and ``syslog_source`` maps that socket's
port back to the device's management address (on 127.0.0.1 every datagram comes from the
same address, so the events receiver gets this mapping instead of the real source).
"""

import socket
import threading
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

from netops_fakes.device import FakeCiscoDevice, FakeFleet, lab_devices
from netops_fakes.lab import Lab
from netops_fakes.live import LiveLab
from netops_fakes.scenarios import Change, record
from netops_fakes.syslog import change_messages, format_message, send
from netops_fakes.topology import Topology

_CLOSED_PORT = 9  # discard; nothing listens there on a test machine


class LocalLab:
    def __init__(self, topology: Topology, username: str, password: str) -> None:
        self.live = LiveLab(topology)
        self.devices: dict[str, FakeCiscoDevice] = lab_devices(self.live, username, password)
        self.fleet = FakeFleet(self.devices.values())
        self.targets: dict[str, int] = {}
        self.connections: list[str] = []
        self._lock = threading.Lock()
        self._syslog_sockets: dict[str, socket.socket] = {}
        self._syslog_sources: dict[int, str] = {}
        self._sequence = 100

    @property
    def lab(self) -> Lab:
        return self.live.lab()

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
        for sock in self._syslog_sockets.values():
            sock.close()
        self._syslog_sockets.clear()

    def resolve(self, host: str, port: int) -> tuple[str, int]:
        with self._lock:
            self.connections.append(host)
        return "127.0.0.1", self.targets.get(host, _CLOSED_PORT)

    # --- changes and syslog --------------------------------------------------------------------

    def apply(self, change: Change, user: str, at: datetime | None = None) -> None:
        self.live.update(record(change, user, at or datetime.now(UTC)))

    def syslog_source(self, address: tuple[str, int]) -> str:
        """Source resolver for the events receiver: (127.0.0.1, port) -> management IP."""
        return self._syslog_sources.get(address[1], address[0])

    def send_syslog(
        self, device: str, messages: list[str], target: tuple[str, int], at: datetime | None = None
    ) -> None:
        sock = self._syslog_sockets.get(device)
        if sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("127.0.0.1", 0))
            self._syslog_sockets[device] = sock
            self._syslog_sources[sock.getsockname()[1]] = str(
                self.live.topology.device(device).mgmt_ip
            )
        when = at or datetime.now(UTC)
        definition = self.live.topology.device(device)
        datagrams = []
        for text in messages:
            self._sequence += 1
            datagrams.append(format_message(definition, self._sequence, when, text))
        send(datagrams, target, sock)

    def change(
        self,
        change: Change,
        target: tuple[str, int] | None,
        user: str = "jdoe",
        source_ip: str = "192.0.2.77",
    ) -> None:
        """Apply ``change`` and, with a ``target``, send its syslog from the device."""
        self.apply(change, user)
        if target is not None:
            self.send_syslog(change.device, change_messages(change, user, source_ip), target)

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
