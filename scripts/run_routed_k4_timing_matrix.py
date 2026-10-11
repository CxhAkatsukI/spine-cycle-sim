#!/usr/bin/env python3
"""Execute every row of the versioned routed SSSP timing diagnostic matrix."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spine_cycle_sim.experiments.sharded_k4_stages.sst_campaign import run_timing_matrix


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("integration", "plugin-dir", "exporter", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--contract", type=Path,
                        default=ROOT / "configs/experiments/sharded_k4_routed_sssp_timing_v1.json")
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    result = run_timing_matrix(root=ROOT, integration=args.integration.resolve(),
                              plugin_dir=args.plugin_dir.resolve(), exporter=args.exporter.resolve(),
                              contract=args.contract.resolve(), output=args.output.resolve(), jobs=args.jobs)
    print(result["status"], flush=True)
    return int(result["status"] == "MATRIX_HAS_FAILURES")


if __name__ == "__main__":
    raise SystemExit(main())
