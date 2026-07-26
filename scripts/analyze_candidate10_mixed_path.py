#!/usr/bin/env python3
"""Validate and attribute the Candidate10 one-fast/one-full tile workload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.mixed_path_analysis import analyze_files  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spine-result", type=Path, required=True)
    parser.add_argument("--maintenance-result", type=Path, required=True)
    parser.add_argument("--hardware-csv", type=Path, required=True)
    parser.add_argument("--frequency-mhz", type=float, default=150.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze_files(
        args.spine_result,
        args.maintenance_result,
        args.hardware_csv,
        frequency_mhz=args.frequency_mhz,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    timing = result["simulator_timing"]
    print(
        f"PASS {result['path_class']}: B={timing['maintenance_cycles']} "
        f"D={timing['first_d_core_span_cycles']} total={timing['total_cycles']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
