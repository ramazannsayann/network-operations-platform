"""Serve one fake device of a topology over SSH (the fakelab containers' entry point).

    python -m netops_fakes.serve /lab/topology.yaml core1 [--host 0.0.0.0] [--port 22]

The password comes from FAKELAB_PASSWORD (never from the command line), the username from
FAKELAB_USERNAME (default ``netops-ro``). Devices with ``credentials: wrong`` accept no
password at all. A device reachable through two addresses runs as two containers.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from netops_fakes.device import lab_devices
from netops_fakes.lab import build
from netops_fakes.topology import load

logger = logging.getLogger("netops_fakes.serve")


async def serve(topology: Path, name: str, host: str, port: int) -> None:
    password = os.environ.get("FAKELAB_PASSWORD", "")
    if not password:
        sys.exit("FAKELAB_PASSWORD is not set")
    username = os.environ.get("FAKELAB_USERNAME", "netops-ro")
    lab = build(load(topology))
    devices = lab_devices(lab, username, password, host=host, port=port)
    if name not in devices:
        sys.exit(f"{name!r} is not a served device of {topology} ({', '.join(sorted(devices))})")
    device = devices[name]
    await device.listen()
    logger.info("fake device %s listening on %s:%s", name, host, device.port)
    await asyncio.Event().wait()  # until the container is stopped


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("topology", type=Path)
    parser.add_argument("device")
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104 - inside its container
    parser.add_argument("--port", type=int, default=22)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("asyncssh").setLevel(logging.WARNING)
    asyncio.run(serve(args.topology, args.device, args.host, args.port))


if __name__ == "__main__":
    main()
