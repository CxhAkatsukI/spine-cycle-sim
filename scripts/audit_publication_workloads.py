#!/usr/bin/env python3
"""Audit complete original temporal candidates and publication denominators."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spine_cycle_sim.experiments.publication_admission.study import collect, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", choices=("AU", "SU", "WK"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        contract = json.loads((ROOT / "configs/experiments/grasu_publication_workload_admission_v1.json").read_text())
        collect(contract, args.worker, args.source_root.resolve(), args.out.resolve())
        return 0
    report = run(ROOT, args.source_root.resolve(), args.out.resolve())
    print(report["status"], flush=True)
    return int(report["status"] == "FAILED")


if __name__ == "__main__":
    raise SystemExit(main())
