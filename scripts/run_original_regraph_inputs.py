#!/usr/bin/env python3
"""Capture original ReGraph host layouts, not accelerator timing."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.original_regraph_inputs.analysis import STATUS  # noqa: E402
from spine_cycle_sim.experiments.original_regraph_inputs.study import run_study  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=ROOT / "configs/experiments/original_regraph_inputs_v1.json")
    parser.add_argument("--source-root", type=Path, default=ROOT / "build/publication_sources")
    parser.add_argument("--xrt-include", type=Path, default=Path("/opt/xilinx/xrt/include"))
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run_study(ROOT, args.contract.resolve(), args.source_root.resolve(), args.out.resolve(),
                        args.compiler, args.xrt_include.resolve())
    print(f"{report['status']}: {args.out.resolve() / 'report.json'}")
    return 0 if report["status"] == STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
