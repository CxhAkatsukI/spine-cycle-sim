"""Launch a fresh, independently guarded author-source topology control."""

import argparse
from pathlib import Path

from .execution import run
from .configuration import DEFAULT_TOPOLOGY, TOPOLOGIES

parser = argparse.ArgumentParser(description=__doc__)
for name in ("upstream", "audit", "control", "environment", "output"):
    parser.add_argument("--" + name, type=Path, required=True)
parser.add_argument("--wait-seconds", type=int, default=0,
                    help="poll finite memory budgets before starting; zero fails immediately")
parser.add_argument("--topology", choices=tuple(TOPOLOGIES), default=DEFAULT_TOPOLOGY)
args = parser.parse_args()
if not 0 <= args.wait_seconds <= 86400:
    parser.error("--wait-seconds must be between zero and 86400")
root = Path(__file__).resolve().parents[5]
paths = [getattr(args, name).resolve() for name in (
    "upstream", "audit", "control", "environment", "output")]
if args.wait_seconds:
    from .waiting import run as wait_and_run
    result = wait_and_run(root, *paths, wait_seconds=args.wait_seconds, topology=args.topology)
else:
    result = run(root, *paths, topology=args.topology)
print(result["status"], flush=True)
