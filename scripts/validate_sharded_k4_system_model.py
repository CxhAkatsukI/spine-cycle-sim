#!/usr/bin/env python3
"""Validate the complete dedicated-four-source SSSP candidate, not FPGA timing."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spine_cycle_sim.experiments.sharded_k4_stages.model_system import validate_system

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate_system(ROOT, args.core_build.resolve(), args.output.resolve())
    print(result["status"] + ": complete SSSP candidate gates; not FPGA timing or SST-profile admission")
