"""Apply a change scenario to the running fake lab and send the matching syslog.

    python -m netops_fakes.change apply /lab/topology.yaml dist1 remove-vlan-from-trunk \\
        [--port Gi1/0/2] [--vlan 20] [--text "..."] [--user jdoe] [--source-ip 192.0.2.77]
    python -m netops_fakes.change reset /lab/topology.yaml
    python -m netops_fakes.change list

``make fakelab-change DEVICE=dist1 SCENARIO=remove-vlan-from-trunk`` runs ``apply`` inside
the device's own container, so the syslog messages leave from the device's management
address and reach the events service (the topology's ``syslog_host``) like a real
device's. The new topology goes to the state file every fake device reads
(FAKELAB_STATE, default /lab/state/topology.json). ``reset`` restores the topology file's
state without sending syslog: the next backup records the revert as a change by an
unknown user.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from netops_fakes.live import LiveLab
from netops_fakes.scenarios import SCENARIOS, ScenarioError, record, run_scenario
from netops_fakes.syslog import change_messages, format_message, send
from netops_fakes.topology import load

DEFAULT_STATE = Path("/lab/state/topology.json")
SYSLOG_PORT = 514


def _apply(args: argparse.Namespace) -> None:
    live = LiveLab(load(args.topology), args.state)
    topology = live.topology
    try:
        change = run_scenario(
            topology, args.device, args.scenario, port=args.port, vlan=args.vlan, text=args.text
        )
    except ScenarioError as exc:
        sys.exit(f"cannot apply {args.scenario} to {args.device}: {exc}")
    now = datetime.now(UTC)
    live.update(record(change, args.user, now))
    print(f"{args.device}: {args.scenario} applied", *change.commands, sep="\n  ")  # noqa: T201
    if args.no_syslog:
        return
    if topology.syslog_host is None and args.syslog is None:
        sys.exit("the topology has no syslog_host; pass --syslog HOST[:PORT] or --no-syslog")
    host, _, port = (args.syslog or str(topology.syslog_host)).partition(":")
    device = topology.device(args.device)
    messages = change_messages(change, args.user, args.source_ip)
    first = 100 + 10 * len(topology.history)  # the device's syslog message counter
    datagrams = [format_message(device, first + i, now, text) for i, text in enumerate(messages)]
    send(datagrams, (host, int(port or SYSLOG_PORT)))
    print(f"sent {len(datagrams)} syslog messages to {host}:{port or SYSLOG_PORT}")  # noqa: T201


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Change the running fake lab.")
    commands = parser.add_subparsers(dest="command", required=True)
    apply = commands.add_parser("apply", help="apply a scenario and send its syslog")
    apply.add_argument("topology", type=Path)
    apply.add_argument("device")
    apply.add_argument("scenario", choices=sorted(SCENARIOS))
    apply.add_argument("--port")
    apply.add_argument("--vlan", type=int)
    apply.add_argument("--text")
    apply.add_argument("--user", default="jdoe")
    apply.add_argument("--source-ip", default="192.0.2.77")
    apply.add_argument("--syslog", help="HOST[:PORT] (default: the topology's syslog_host)")
    apply.add_argument("--no-syslog", action="store_true")
    apply.add_argument("--state", type=Path, default=DEFAULT_STATE)
    reset = commands.add_parser("reset", help="restore the topology file's state")
    reset.add_argument("topology", type=Path)
    reset.add_argument("--state", type=Path, default=DEFAULT_STATE)
    commands.add_parser("list", help="list the scenarios")
    args = parser.parse_args(argv)

    if args.command == "apply":
        _apply(args)
    elif args.command == "reset":
        LiveLab(load(args.topology), args.state).reset()
        print("fake lab reset to", args.topology)  # noqa: T201
    else:
        print("\n".join(sorted(SCENARIOS)))  # noqa: T201


if __name__ == "__main__":
    main()
