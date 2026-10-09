#!/usr/bin/env python3
"""Run the bounded, separately admitted finite PMA/original-A4 control."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.pma_adapter.study import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("adapter-source", "hls-packet", "hls-include", "input-run", "baseline", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    report = run(ROOT, *(getattr(args, name).resolve() for name in
        ("adapter_source", "hls_packet", "hls_include", "input_run", "baseline", "out")))
    print(report["status"])
    return 0 if report["status"] == "FINITE_A4_B_FUNCTIONAL_PASS_TIMING_PREDICTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
