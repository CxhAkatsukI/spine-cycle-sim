"""Explicitly request the conditional original-R board-control matrix."""

import argparse
from pathlib import Path

from .supervisor import run
from ..source_build.configuration import DEFAULT_TOPOLOGY, TOPOLOGIES

parser = argparse.ArgumentParser(description=__doc__)
for name in ("audit", "control", "route", "output"):
    parser.add_argument("--" + name, type=Path, required=True)
parser.add_argument("--route-unit", required=True)
parser.add_argument("--route-invocation", required=True)
parser.add_argument("--device", type=int, choices=(0, 1), default=1)
parser.add_argument("--topology", choices=TOPOLOGIES, default=DEFAULT_TOPOLOGY)
parser.add_argument("--maximum-wait", type=float, default=86400)
parser.add_argument("--poll-seconds", type=float, default=30)
parser.add_argument("--execute", action="store_true", required=True)
args = parser.parse_args()
print(run(*(path.resolve() for path in (args.audit, args.control, args.route, args.output)),
    route_unit=args.route_unit, route_invocation=args.route_invocation, device=args.device,
    maximum_wait=args.maximum_wait, poll_seconds=args.poll_seconds, topology=args.topology)["status"], flush=True)
