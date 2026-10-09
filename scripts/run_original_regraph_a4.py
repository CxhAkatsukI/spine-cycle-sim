#!/usr/bin/env python3
"""Run the fixed independent original-A4 whole-graph functional/timing study."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.original_regraph_execution.analysis import STATUS
from spine_cycle_sim.experiments.original_regraph_execution.study import run_study


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=ROOT / "configs/experiments/original_regraph_a4_execution_v1.json")
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--gather-captures", type=Path, help="regenerated original Gather controls; values must match frozen hashes")
    parser.add_argument("--apply-captures", type=Path, help="regenerated original Apply controls; values must match frozen hashes")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run_study(ROOT, args.contract.resolve(), args.inputs.resolve(), args.baseline.resolve(), args.out.resolve(),
        args.gather_captures.resolve() if args.gather_captures else None,
        args.apply_captures.resolve() if args.apply_captures else None)
    print(f"{report['status']}: {args.out / 'report.json'}")
    return 0 if report["status"] == STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
