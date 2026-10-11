#!/usr/bin/env python3
"""Freeze completed adapter pre-route, paired-board or model gates separately."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine_cycle_sim.experiments.sharded_k4_stages.optimization_delivery import package_pre_route
from spine_cycle_sim.experiments.sharded_k4_stages.board_delivery import package_board
from spine_cycle_sim.experiments.sharded_k4_stages.model_delivery import package_model_adapter
from spine_cycle_sim.experiments.sharded_k4_stages.compute_delivery import package_model_compute
from spine_cycle_sim.experiments.sharded_k4_stages.frontend_delivery import package_model_frontend

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "integration", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--board-case", action="append", help="completed paired-run child directory; repeat for each case")
    parser.add_argument("--model-adapter", action="store_true", help="package model-component and legacy-regression gates")
    parser.add_argument("--model-compute", action="store_true", help="package compute extraction and shared-port gates")
    parser.add_argument("--model-frontend", action="store_true", help="package source artifact and frontend component gates")
    args = vars(parser.parse_args())
    model = args.pop("model_adapter")
    compute = args.pop("model_compute")
    frontend = args.pop("model_frontend")
    if sum((model, compute, frontend, bool(args["board_case"]))) > 1:
        parser.error("model and board evidence require separate packages")
    if frontend:
        args.pop("board_case")
        result = package_model_frontend(**args)
    elif compute:
        args.pop("board_case")
        result = package_model_compute(**args)
    elif model:
        args.pop("board_case")
        result = package_model_adapter(**args)
    elif args["board_case"]:
        result = package_board(**args)
    else:
        args.pop("board_case")
        result = package_pre_route(**args)
    print(result["status"])
