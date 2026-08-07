#!/usr/bin/env python3
"""Analyze the five-dataset GraSU temporal batch-8 Full PageRank matrix."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.temporal_real_analysis import (  # noqa: E402
    analyze_temporal_full_pagerank,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-dir", type=Path, required=True)
    parser.add_argument(
        "--input-manifest",
        type=Path,
        default=ROOT
        / "configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--paper-data-dir", type=Path)
    args = parser.parse_args()
    report = analyze_temporal_full_pagerank(
        matrix_dir=args.matrix_dir,
        input_manifest_path=args.input_manifest,
        out_dir=args.out_dir,
        paper_data_dir=args.paper_data_dir,
    )
    headline = report["headline"]
    print(
        "PASS temporal Full PageRank analysis: "
        f"pairs={report['pairs']} "
        f"spine_speedup={float(headline['spine_speedup_e2e_geomean']):.4f}x"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
