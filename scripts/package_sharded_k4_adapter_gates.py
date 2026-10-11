#!/usr/bin/env python3
"""Freeze completed adapter pre-route, paired-board or model gates separately."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine_cycle_sim.experiments.sharded_k4_stages.optimization_delivery import package_pre_route
from spine_cycle_sim.experiments.sharded_k4_stages.board_delivery import package_board
from spine_cycle_sim.experiments.sharded_k4_stages.model_delivery import package_model_adapter

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "integration", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--board-case", action="append", help="completed paired-run child directory; repeat for each case")
    parser.add_argument("--model-adapter", action="store_true", help="package model-component and legacy-regression gates")
    args = vars(parser.parse_args())
    model = args.pop("model_adapter")
    if model and args["board_case"]:
        parser.error("model and board evidence require separate packages")
    if model:
        args.pop("board_case")
        result = package_model_adapter(**args)
    elif args["board_case"]:
        result = package_board(**args)
    else:
        args.pop("board_case")
        result = package_pre_route(**args)
    print(result["status"])
