#!/usr/bin/env python3
"""Collect pinned upstream HLS schedules without claiming FPGA measurement."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.upstream_controls.hls_study import run_synthesis_study  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=ROOT / (
        "configs/experiments/grasu_regraph_upstream_synthesis_v1.json"))
    parser.add_argument("--source-pins", type=Path, default=ROOT / (
        "docs/experiments/comparisons/grasu_regraph_stage_validation/source_pins.json"))
    parser.add_argument("--source-root", type=Path, default=ROOT / "build/publication_sources")
    parser.add_argument("--tool", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run_synthesis_study(ROOT, args.contract.resolve(), args.source_pins.resolve(),
                                args.source_root.resolve(), args.out.resolve(), args.tool.resolve())
    print(f"Report: {args.out.resolve() / 'report.json'}")
    return 0 if report["all_synthesized"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
