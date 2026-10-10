#!/usr/bin/env python3
"""Execute the independent source16 finite GraSU composition matrix."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spine_cycle_sim.experiments.grasu_finite.study import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "baseline", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--smoke", action="store_true", help="one empty fixture, not an admitted matrix")
    parser.add_argument("--ubsan-binary", type=Path, help="required for formal matrix admission")
    parser.add_argument("--deliver-to", type=Path)
    parser.add_argument("--attempt", type=Path, action="append", default=[])
    args = parser.parse_args()
    report = run(ROOT, args.binary.resolve(), args.baseline.resolve(), args.out.resolve(), args.smoke,
                 args.ubsan_binary.resolve() if args.ubsan_binary else None)
    print(report["status"])
    if args.deliver_to and report["status"] == "G_FINITE_SOURCE16_STATE_LEDGER_PASS_NOT_TIMING":
        from spine_cycle_sim.experiments.grasu_finite.delivery import deliver
        print(deliver(ROOT, args.out.resolve(), args.deliver_to.resolve(),
                      [path.resolve() for path in args.attempt])["status"])
    return int(report["status"] == "FAILED")


if __name__ == "__main__":
    raise SystemExit(main())
