#!/usr/bin/env python3
"""Validate original Big source-memory/Scatter, not publication throughput."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spine_cycle_sim.experiments.original_regraph_validation.big.frontend_analysis import STATUS  # noqa: E402
from spine_cycle_sim.experiments.original_regraph_validation.big.frontend_study import run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "build/publication_sources/regraph")
    parser.add_argument("--hls-include", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run(ROOT, args.source.resolve(), args.hls_include.resolve(), args.baseline.resolve(), args.out.resolve())
    print(report["status"], report.get("error", ""), args.out.resolve() / "report.json")
    return 0 if report["status"] == STATUS else 1


if __name__ == "__main__": raise SystemExit(main())
