#!/usr/bin/env python3
"""Analyze the 3-algorithm x 3-small-batch x 5-dataset matrix."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.temporal_three_algorithm_analysis import (  # noqa: E402
    analyze_temporal_expanded_small_batches,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-evidence-dir",
        type=Path,
        default=ROOT
        / "docs/evidence/candidate10_grasu_temporal_three_algorithms_insert_u8_20260727",
    )
    parser.add_argument(
        "--full-pagerank-evidence-dir",
        type=Path,
        default=ROOT
        / "docs/evidence/candidate10_grasu_temporal_full_pr_small_batches_20260727",
    )
    parser.add_argument("--weighted-gap-dir", type=Path, required=True)
    parser.add_argument("--residual-gap-dir", type=Path, required=True)
    parser.add_argument(
        "--input-manifest",
        type=Path,
        default=ROOT
        / "configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--paper-data-dir", type=Path)
    args = parser.parse_args()
    report = analyze_temporal_expanded_small_batches(
        baseline_evidence_dir=args.baseline_evidence_dir,
        full_pagerank_evidence_dir=args.full_pagerank_evidence_dir,
        weighted_gap_dir=args.weighted_gap_dir,
        residual_gap_dir=args.residual_gap_dir,
        input_manifest_path=args.input_manifest,
        out_dir=args.out_dir,
        paper_data_dir=args.paper_data_dir,
    )
    print(
        "PASS temporal expanded small batches: "
        f"pairs={report['pairs']} rows={report['system_rows']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
