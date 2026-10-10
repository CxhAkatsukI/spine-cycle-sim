#!/usr/bin/env python3
"""ABI-checked single-XO production K4 link with a memory watchdog."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine_cycle_sim.experiments.sharded_k4_stages.routing import execute_route, prepare_route

parser = argparse.ArgumentParser(description=__doc__)
sub = parser.add_subparsers(dest="action", required=True)
prepare = sub.add_parser("prepare")
for option in ("build", "candidate", "synthesis", "cosim", "output"):
    prepare.add_argument("--" + option, type=Path, required=True)
run = sub.add_parser("run")
run.add_argument("--output", type=Path, required=True)
args = vars(parser.parse_args())
action = args.pop("action")
result = prepare_route(**args) if action == "prepare" else execute_route(**args)
print(result["status"], flush=True)
if result["status"] == "LINK_FAILED":
    sys.exit(1)
