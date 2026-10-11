"""Write the fake lab's running-configs as parser fixtures (the only config fixtures).

    python -m netops_fakes.fixtures ../lab/fakelab/topology.yaml \\
        ../lab/fixtures/cisco_ios/show_running-config

``make fakelab-fixtures`` runs it; a test fails while the committed files are stale. Real
configurations are never committed (ADR-0007): these are generated, with the obviously
fake secrets of netops_fakes.fake_secrets.
"""

import argparse
from pathlib import Path

from netops_fakes.lab import build
from netops_fakes.running_config import show_running_config
from netops_fakes.topology import Topology, load

# One device of each kind: L3 core, IOS-XE distribution, IOS 15 access, router.
DEVICES = ("core1", "dist1", "access1", "rtr1")


def fixtures(topology: Topology) -> dict[str, str]:
    """File name -> content."""
    lab = build(topology)
    return {
        f"netops_fakelab_{name}.raw": show_running_config(lab, lab.devices[name])
        for name in DEVICES
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write the fake lab's config fixtures.")
    parser.add_argument("topology", type=Path)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    args.directory.mkdir(parents=True, exist_ok=True)
    for name, content in fixtures(load(args.topology)).items():
        (args.directory / name).write_text(content)


if __name__ == "__main__":
    main()
