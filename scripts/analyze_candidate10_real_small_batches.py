#!/usr/bin/env python3
"""Combine the three Candidate10 v3 real small-batch comparison matrices."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.real_small_batch_analysis import (  # noqa: E402
    analyze_real_small_batches,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weighted-dir", type=Path, required=True)
    parser.add_argument("--full-pagerank-dir", type=Path, required=True)
    parser.add_argument("--residual-pagerank-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    result = analyze_real_small_batches(
        {
            "weighted_sssp": args.weighted_dir,
            "full_pagerank": args.full_pagerank_dir,
            "thresholded_residual_pagerank": args.residual_pagerank_dir,
        },
        args.out_dir,
    )
    overall = result["group_summary"][0]
    print(
        "PASS Candidate10 real small batches: "
        f"rows={result['system_rows']} pairs={result['pairs']} "
        f"e2e_geomean={overall['spine_speedup_over_grasu_e2e_geomean']:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
