#!/usr/bin/env python3
"""Check isolated original GraSU DDR RTL against source under shared memory."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spine_cycle_sim.experiments.grasu_ddr_rtl.study import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("hls-tool", "simulator-bin", "hls-include", "baseline", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--deliver-to", type=Path)
    parser.add_argument("--attempt", type=Path, action="append", default=[])
    parser.add_argument("--capture-baseline", action="store_true", help="freeze current old code/evidence into a new baseline path")
    args = parser.parse_args()
    if args.capture_baseline:
        from spine_cycle_sim.experiments.grasu_ddr_rtl.preparation import capture_baseline
        capture_baseline(ROOT, args.baseline.resolve())
    report = run(ROOT, *(getattr(args, name).resolve() for name in ("hls_tool", "simulator_bin", "hls_include", "baseline", "out")))
    print(report["status"])
    if args.deliver_to and report["status"] != "FAILED":
        from spine_cycle_sim.experiments.grasu_ddr_rtl.delivery import deliver
        print(deliver(ROOT, args.out.resolve(), args.deliver_to.resolve(), [path.resolve() for path in args.attempt])["status"])
    return int(report["status"] == "FAILED")


if __name__ == "__main__":
    raise SystemExit(main())
