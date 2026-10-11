"""The fake lab as it is now: a base topology plus the changes applied to it.

Fake devices answer from a ``LiveLab``, so a change shows up in every output of every
device at once. In the fakelab containers the current topology lives in a JSON state file
on a volume all fake devices mount (written by ``python -m netops_fakes.change``, read
again whenever it changes); in tests it lives in memory (``LocalLab.apply``).
"""

import json
import os
import threading
from collections.abc import Iterator, Mapping
from pathlib import Path

from netops_fakes.lab import Lab, build
from netops_fakes.render import render
from netops_fakes.topology import Topology


class LiveLab:
    def __init__(self, base: Topology, state_file: Path | None = None) -> None:
        self.base = base
        self.state_file = state_file
        self._lock = threading.Lock()
        self._topology = base
        self._stamp: tuple[int, int] | None = None
        self._lab: Lab | None = None
        self._outputs: dict[str, dict[str, str]] = {}

    def _file_stamp(self) -> tuple[int, int] | None:
        if self.state_file is None:
            return None
        try:
            stat = self.state_file.stat()
        except FileNotFoundError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _refresh(self) -> None:
        """Reload the state file if it changed (called with the lock held)."""
        if self.state_file is None:
            return
        stamp = self._file_stamp()
        if stamp == self._stamp and self._lab is not None:
            return
        topology = self.base
        if stamp is not None:
            topology = Topology.model_validate(json.loads(self.state_file.read_text()))
        self._set(topology)
        self._stamp = stamp

    def _set(self, topology: Topology) -> None:
        self._topology = topology
        self._lab = None
        self._outputs = {}

    @property
    def topology(self) -> Topology:
        with self._lock:
            self._refresh()
            return self._topology

    def lab(self) -> Lab:
        with self._lock:
            self._refresh()
            if self._lab is None:
                self._lab = build(self._topology)
            return self._lab

    def outputs(self, device: str) -> dict[str, str]:
        lab = self.lab()
        with self._lock:
            if device not in self._outputs:
                self._outputs[device] = render(lab, lab.devices[device])
            return self._outputs[device]

    def update(self, topology: Topology) -> None:
        """Make ``topology`` the current one (and persist it for the other devices)."""
        build(topology)  # refuse a topology the lab cannot be built from
        with self._lock:
            if self.state_file is not None:
                temporary = self.state_file.with_suffix(".tmp")
                temporary.write_text(json.dumps(topology.model_dump(mode="json"), indent=1))
                os.replace(temporary, self.state_file)
                self._stamp = self._file_stamp()
            self._set(topology)

    def reset(self) -> None:
        with self._lock:
            if self.state_file is not None:
                self.state_file.unlink(missing_ok=True)
                self._stamp = None
            self._set(self.base)


class LiveOutputs(Mapping[str, str]):
    """One device's command outputs, always from the lab's current state."""

    def __init__(self, live: LiveLab, device: str) -> None:
        self.live = live
        self.device = device

    def __getitem__(self, command: str) -> str:
        return self.live.outputs(self.device)[command]

    def __iter__(self) -> Iterator[str]:
        return iter(self.live.outputs(self.device))

    def __len__(self) -> int:
        return len(self.live.outputs(self.device))
