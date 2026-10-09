#!/usr/bin/env python3
"""Run the fixed 11-Little/3-Big graph iteration, with explicit tail padding."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.original_regraph_execution.mixed.analysis import STATUS
from spine_cycle_sim.experiments.original_regraph_execution.mixed.study import run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run(ROOT, args.inputs.resolve(), args.baseline.resolve(), args.out.resolve())
    print(f"{report['status']}: {args.out / 'report.json'}")
    return 0 if report["status"] == STATUS else 1


if __name__ == "__main__": raise SystemExit(main())
