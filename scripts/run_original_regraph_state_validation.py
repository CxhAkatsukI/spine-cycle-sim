#!/usr/bin/env python3
"""Validate original PR state components and resident A4 iterations, not speed matching."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.original_regraph_validation.state_analysis import STATUS  # noqa: E402
from spine_cycle_sim.experiments.original_regraph_validation.state_study import run_state_study  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path,
                        default=ROOT / "configs/experiments/original_regraph_state_validation_v1.json")
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--apply-captures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run_state_study(ROOT, args.contract.resolve(), args.captures.resolve(), args.protocol.resolve(),
                             args.apply_captures.resolve(), args.out.resolve())
    print(f"{report['status']}: {args.out.resolve() / 'report.json'}")
    return 0 if report["status"] == STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
