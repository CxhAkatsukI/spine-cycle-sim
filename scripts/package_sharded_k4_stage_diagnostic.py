#!/usr/bin/env python3
"""Freeze a completed actual-K4 diagnostic into its documentation owner."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine_cycle_sim.experiments.sharded_k4_stages.delivery import package


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(package(args.data, args.output)["status"])
