#!/usr/bin/env python3
"""Validate and summarize a completed normalized shared comparison matrix."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.comparison_analysis import (  # noqa: E402
    analyze_completed_matrix,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    result = analyze_completed_matrix(args.matrix_dir.resolve(), args.out_dir.resolve())
    overall = result["group_summary"][0]
    print(
        "PASS shared comparison analysis: "
        f"rows={result['system_rows']} pairs={result['pairs']} "
        f"speedup_geomean={overall['speedup_geomean']:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
