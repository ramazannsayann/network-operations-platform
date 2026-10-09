"""Fake Cisco IOS devices: SSH servers that answer ``show`` commands with prepared output.

Written instead of using FakeNOS: FakeNOS pins ``paramiko<=4.0``, which uv would apply to the
whole lock file (so also to Netmiko in production), and pulls in a dated ``detect`` package;
the behaviour needed here fits in ~100 lines on top of asyncssh.

Behaviour: password authentication, a ``<hostname>>`` prompt, ``terminal length 0`` /
``terminal width N`` accepted silently, prepared output for known commands and
``% Invalid input detected`` for anything else (like IOS). Every command received is kept
in ``commands`` so tests can prove what was (not) sent, every failed login is counted.

Tests serve devices on 127.0.0.1 (random ports); the fakelab containers bind 0.0.0.0:22.
Many devices can share one event loop thread (FakeFleet), so a 200-device topology needs
one thread, not 200.
"""

import asyncio
import contextlib
import secrets
import threading
from collections.abc import Coroutine, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncssh

from netops_fakes.lab import Lab
from netops_fakes.render import render
from netops_fakes.topology import Credentials

INVALID_INPUT = "                    ^\n% Invalid input detected at '^' marker.\n\n"
_SILENT = ("terminal length 0", "terminal width ")


def load_outputs(directory: Path) -> dict[str, str]:
    """``show_ip_route.raw`` -> ``{"show ip route": <text>}``."""
    return {path.stem.replace("_", " "): path.read_text() for path in directory.glob("*.raw")}


@dataclass
class FakeCiscoDevice:
    hostname: str
    username: str
    password: str
    outputs: Mapping[str, str]
    host: str = "127.0.0.1"
    port: int = 0  # 0: a free port, set by listen()
    commands: list[str] = field(default_factory=list)
    sessions: int = 0
    failed_logins: int = 0
    _server: asyncssh.SSHAcceptor | None = field(default=None, repr=False)
    _connections: set[asyncssh.SSHServerConnection] = field(default_factory=set, repr=False)
    _loop: "_LoopThread | None" = field(default=None, repr=False)

    def __repr__(self) -> str:
        return f"FakeCiscoDevice({self.hostname!r}, {self.host}:{self.port})"

    def start(self) -> int:
        """Listen in a background thread of its own; returns the port."""
        self._loop = _LoopThread()
        return self._loop.run(self.listen())

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.run(self.close())
            self._loop.stop()
            self._loop = None

    async def listen(self) -> int:
        """Start serving on the running event loop; returns the port."""
        device = self

        class Server(asyncssh.SSHServer):
            def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
                self._conn = conn
                device._connections.add(conn)

            def connection_lost(self, exc: Exception | None) -> None:
                device._connections.discard(self._conn)

            def begin_auth(self, username: str) -> bool:
                return True

            def password_auth_supported(self) -> bool:
                return True

            def validate_password(self, username: str, password: str) -> bool:
                ok = username == device.username and password == device.password
                if not ok:
                    device.failed_logins += 1
                return ok

        # A throwaway host key per device: no key material is stored in the repository.
        self._server = await asyncssh.create_server(
            Server,
            self.host,
            self.port,
            server_host_keys=[asyncssh.generate_private_key("ssh-ed25519")],
            process_factory=self._shell,
        )
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            # Since Python 3.12 wait_closed() also waits for open client connections.
            for conn in list(self._connections):
                conn.abort()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._server.wait_closed(), timeout=5)
            self._server = None

    async def _shell(self, process: asyncssh.SSHServerProcess) -> None:  # type: ignore[type-arg]
        self.sessions += 1
        prompt = f"{self.hostname}>"
        process.stdout.write(f"\n{prompt}")
        try:
            while not process.stdin.at_eof():
                line = await process.stdin.readline()
                if not line and process.stdin.at_eof():
                    break
                command = line.strip()
                if command:
                    self.commands.append(command)
                if command in ("exit", "logout", "quit"):
                    break
                if not command or command.startswith(_SILENT):
                    process.stdout.write(f"\n{prompt}")
                    continue
                output = self.outputs.get(command)
                process.stdout.write(f"\n{output if output is not None else INVALID_INPUT}{prompt}")
        except (asyncssh.BreakReceived, asyncssh.TerminalSizeChanged, ConnectionError):
            pass
        finally:
            process.exit(0)


class _LoopThread:
    """An asyncio event loop running in a daemon thread."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()

    def run[T](self, coroutine: Coroutine[Any, Any, T], timeout: float = 30) -> T:
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=5)


def lab_devices(
    lab: Lab, username: str, password: str, *, host: str = "127.0.0.1", port: int = 0
) -> dict[str, FakeCiscoDevice]:
    """One fake device per served device of ``lab``. Devices configured with
    ``credentials: wrong`` get a random password nobody knows."""
    devices = {}
    for state in lab.served():
        lab_credentials = state.device.credentials is Credentials.LAB
        accepted = password if lab_credentials else secrets.token_urlsafe(24)
        devices[state.name] = FakeCiscoDevice(
            state.name, username, accepted, render(lab, state), host=host, port=port
        )
    return devices


class FakeFleet:
    """Serve many fake devices from one background event loop."""

    def __init__(self, devices: Iterable[FakeCiscoDevice]) -> None:
        self.devices = list(devices)
        self._loop: _LoopThread | None = None

    def start(self) -> "FakeFleet":
        self._loop = _LoopThread()
        self._loop.run(self._listen_all())
        return self

    async def _listen_all(self) -> None:
        await asyncio.gather(*(device.listen() for device in self.devices))

    def stop(self) -> None:
        if self._loop is None:
            return
        loop, self._loop = self._loop, None

        async def close_all() -> None:
            await asyncio.gather(*(device.close() for device in self.devices))

        loop.run(close_all())
        loop.stop()

    def __enter__(self) -> "FakeFleet":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
