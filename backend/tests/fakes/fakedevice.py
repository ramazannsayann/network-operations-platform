"""A minimal fake Cisco IOS device for tests: an SSH server that answers ``show`` commands
with recorded output.

Written instead of using FakeNOS: FakeNOS pins ``paramiko<=4.0``, which uv would apply to the
whole lock file (so also to Netmiko in production), and pulls in a dated ``detect`` package;
the behaviour needed here fits in ~100 lines on top of asyncssh.

Behaviour: password authentication, a ``<hostname>>`` prompt, ``terminal length 0`` /
``terminal width N`` accepted silently, recorded output for known commands and
``% Invalid input detected`` for anything else (like IOS). Every command received is kept
in ``commands`` so tests can prove what was (not) sent. Listens on 127.0.0.1 only.
"""

import asyncio
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import asyncssh

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
    commands: list[str] = field(default_factory=list)
    sessions: int = 0
    failed_logins: int = 0
    port: int = 0
    _loop: asyncio.AbstractEventLoop | None = None
    _thread: threading.Thread | None = None
    _server: asyncssh.SSHAcceptor | None = None

    def start(self) -> int:
        """Start listening on 127.0.0.1 (random port) in a background thread."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        future = asyncio.run_coroutine_threadsafe(self._listen(), self._loop)
        self.port = future.result(timeout=10)
        return self.port

    def stop(self) -> None:
        if self._loop is None:
            return
        if self._server is not None:
            self._loop.call_soon_threadsafe(self._server.close)
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)

    async def _listen(self) -> int:
        device = self

        class Server(asyncssh.SSHServer):
            def begin_auth(self, username: str) -> bool:
                return True

            def password_auth_supported(self) -> bool:
                return True

            def validate_password(self, username: str, password: str) -> bool:
                ok = username == device.username and password == device.password
                if not ok:
                    device.failed_logins += 1
                return ok

        # A throwaway host key per run: no key material is stored in the repository.
        self._server = await asyncssh.create_server(
            Server,
            "127.0.0.1",
            0,
            server_host_keys=[asyncssh.generate_private_key("ssh-ed25519")],
            process_factory=self._shell,
        )
        port: int = self._server.sockets[0].getsockname()[1]
        return port

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
