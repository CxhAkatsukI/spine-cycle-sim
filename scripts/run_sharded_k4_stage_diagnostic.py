#!/usr/bin/env python3
"""Thin CLI for actual sharded-K4 hardware event diagnostics."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine_cycle_sim.experiments.sharded_k4_stages.execution import run_study


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("integration", "matrix", "baseline-host", "trace-host", "output"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--memory-gib", type=int, default=8)
    arguments = vars(parser.parse_args())
    print(run_study(**arguments)["status"])


if __name__ == "__main__":
    main()
