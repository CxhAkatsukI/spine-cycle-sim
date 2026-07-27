#!/usr/bin/env python3
"""Analyze five-dataset batch 1/8/64 Full PageRank evidence."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.temporal_real_analysis import (  # noqa: E402
    analyze_temporal_small_batch_pagerank,
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
    report = analyze_temporal_small_batch_pagerank(
        matrix_dir=args.matrix_dir,
        input_manifest_path=args.input_manifest,
        out_dir=args.out_dir,
        paper_data_dir=args.paper_data_dir,
    )
    print(
        "PASS temporal Full PageRank small batches: "
        f"pairs={report['pairs']} batches={report['batch_sizes']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
