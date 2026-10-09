#!/usr/bin/env python3
"""Validate original ReGraph finite Gather/merge; no whole-R speed claim."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.original_regraph_validation.study import run_study  # noqa: E402
from spine_cycle_sim.experiments.original_regraph_validation.delivery import deliver  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path,
                        default=ROOT / "configs/experiments/original_regraph_gather_validation_v1.json")
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--deliver-to", type=Path)
    args = parser.parse_args()
    report = run_study(ROOT, args.contract.resolve(), args.captures.resolve(), args.out.resolve())
    print(f"{report['status']}: {args.out.resolve() / 'report.json'}")
    if args.deliver_to and report["status"] == "FINITE_GATHER_MERGE_FUNCTIONAL_PASS_TIMING_PREDICTED":
        record = deliver(ROOT, args.captures.resolve(), args.out.resolve(), args.deliver_to.resolve())
        print(f"Packaged {len(record['files'])} raw evidence files in {args.deliver_to.resolve()}")
    return 0 if report["status"] == "FINITE_GATHER_MERGE_FUNCTIONAL_PASS_TIMING_PREDICTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
