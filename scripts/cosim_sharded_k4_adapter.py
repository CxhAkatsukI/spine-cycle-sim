#!/usr/bin/env python3
"""Run source-pinned original/candidate adapter RTL co-simulation."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine_cycle_sim.experiments.sharded_k4_stages.rtl import cosimulate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("weighted", "destination", "unit"), default="weighted")
    args = parser.parse_args()
    print(cosimulate(args.integration, args.output, mode=args.mode)["status"])
