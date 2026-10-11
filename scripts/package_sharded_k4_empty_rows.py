#!/usr/bin/env python3
"""Validate and freeze the complete bounded empty-row diagnostic."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spine_cycle_sim.experiments.sharded_k4_stages.row_sweep_delivery import package_sweep


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    result = package_sweep(ROOT, args.data.resolve(), args.output.resolve())
    print(result["status"], flush=True)


if __name__ == "__main__":
    main()
