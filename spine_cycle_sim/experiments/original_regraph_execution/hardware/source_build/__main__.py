"""Launch a fresh, independently guarded author-source topology control."""

import argparse
from pathlib import Path

from .execution import run
from .configuration import ALGORITHMS, DEFAULT_TOPOLOGY, TOPOLOGIES
from . import placement

parser = argparse.ArgumentParser(description=__doc__)
for name in ("upstream", "audit", "environment", "output"):
    parser.add_argument("--" + name, type=Path, required=True)
parser.add_argument("--control", type=Path, help="guarded offline host validation, required only for PR")
parser.add_argument("--wait-seconds", type=int, default=0,
                    help="poll finite memory budgets before starting; zero fails immediately")
parser.add_argument("--topology", choices=tuple(TOPOLOGIES), default=DEFAULT_TOPOLOGY)
parser.add_argument("--placement", choices=placement.CHOICES, default=placement.DEFAULT)
parser.add_argument("--algorithm", choices=ALGORITHMS, default="pr")
parser.add_argument("--weighted-udf", type=Path)
args = parser.parse_args()
if not 0 <= args.wait_seconds <= 86400:
    parser.error("--wait-seconds must be between zero and 86400")
if (args.control is not None) != (args.algorithm == "pr"):
    parser.error("--control must be supplied for PR only")
root = Path(__file__).resolve().parents[5]
control = args.control.resolve() if args.control is not None else None
paths = (args.upstream.resolve(), args.audit.resolve(), control,
         args.environment.resolve(), args.output.resolve())
options = {"topology": args.topology, "placement": args.placement, "algorithm": args.algorithm,
           "weighted_udf": args.weighted_udf.resolve() if args.weighted_udf else None}
if args.wait_seconds:
    from .waiting import run as wait_and_run
    result = wait_and_run(root, *paths, wait_seconds=args.wait_seconds, **options)
else:
    result = run(root, *paths, **options)
print(result["status"], flush=True)
