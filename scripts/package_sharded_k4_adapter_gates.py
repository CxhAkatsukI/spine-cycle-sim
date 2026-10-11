#!/usr/bin/env python3
"""Freeze completed adapter pre-route or paired-board gates separately."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine_cycle_sim.experiments.sharded_k4_stages.optimization_delivery import package_pre_route
from spine_cycle_sim.experiments.sharded_k4_stages.board_delivery import package_board

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "integration", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--board-case", action="append", help="completed paired-run child directory; repeat for each case")
    args = vars(parser.parse_args())
    if args["board_case"]:
        result = package_board(**args)
    else:
        args.pop("board_case")
        result = package_pre_route(**args)
    print(result["status"])
