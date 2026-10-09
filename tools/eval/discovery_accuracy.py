"""Discovery accuracy: compare the inventory with a topology file (proposal section 9).

Prints device and link precision/recall, every miss and false positive, and the role
heuristic's result for devices with an expected role. Works for the fake lab and for the
real lab's topology file (same format; only `devices` and `links` matter, see
backend/src/netops_fakes/topology.py).

    make fakelab-accuracy
    # or, against any database the backend settings point at (POSTGRES_* variables):
    cd backend && uv run python ../tools/eval/discovery_accuracy.py ../lab/fakelab/topology.yaml

Exit status: 0 when precision and recall are 100% for devices and links, 1 otherwise.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from netops.core.settings import get_settings
from netops.db.session import create_engine
from netops_fakes.accuracy import Accuracy, evaluate
from netops_fakes.topology import load


async def measure(topology_file: Path) -> Accuracy:
    topology = load(topology_file)
    engine = create_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await evaluate(session, topology)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare discovery results with a topology.")
    parser.add_argument("topology", type=Path, help="topology file, e.g. lab/fakelab/topology.yaml")
    args = parser.parse_args()
    accuracy = asyncio.run(measure(args.topology))
    print(f"Discovery accuracy against {args.topology}")  # noqa: T201
    print(accuracy.report())  # noqa: T201
    return 0 if accuracy.perfect else 1


if __name__ == "__main__":
    sys.exit(main())
