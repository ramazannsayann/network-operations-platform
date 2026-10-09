"""Write the OpenAPI document (the API contract) to a file, or check that it is current.

python -m netops.api.export_openapi ../docs/api/openapi.json          # write
python -m netops.api.export_openapi --check ../docs/api/openapi.json  # CI: fail if stale
"""

import argparse
import json
import sys
from pathlib import Path

from netops.api.app import build_api


def render() -> str:
    return json.dumps(build_api().openapi(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("path", type=Path, help="where the OpenAPI JSON document lives")
    parser.add_argument("--check", action="store_true", help="only compare; exit 1 if stale")
    args = parser.parse_args(argv)

    document = render()
    if args.check:
        current = args.path.read_text(encoding="utf-8") if args.path.exists() else ""
        if current != document:
            sys.stderr.write(f"{args.path} is out of date; run `make openapi` and commit it.\n")
            return 1
        return 0
    args.path.parent.mkdir(parents=True, exist_ok=True)
    args.path.write_text(document, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
