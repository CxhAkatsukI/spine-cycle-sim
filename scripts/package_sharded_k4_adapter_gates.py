#!/usr/bin/env python3
"""Freeze adapter RTL/HLS evidence without absorbing a running route job."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine_cycle_sim.experiments.sharded_k4_stages.optimization_delivery import package_pre_route

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "integration", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    print(package_pre_route(**vars(parser.parse_args()))["status"])
