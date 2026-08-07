#!/usr/bin/env python3
"""Analyze four differential-update scenarios on five temporal slices."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.temporal_real_analysis import (  # noqa: E402
    analyze_temporal_differential_pagerank,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-evidence-dir",
        type=Path,
        default=ROOT
        / "docs/evidence/candidate10_grasu_temporal_full_pr_batch8_20260727",
    )
    parser.add_argument("--weight-change-matrix-dir", type=Path, required=True)
    parser.add_argument(
        "--input-manifest",
        type=Path,
        default=ROOT
        / "configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--paper-data-dir", type=Path)
    args = parser.parse_args()
    report = analyze_temporal_differential_pagerank(
        baseline_evidence_dir=args.baseline_evidence_dir,
        weight_change_matrix_dir=args.weight_change_matrix_dir,
        input_manifest_path=args.input_manifest,
        out_dir=args.out_dir,
        paper_data_dir=args.paper_data_dir,
    )
    print(
        "PASS temporal Full PageRank differential matrix: "
        f"pairs={report['pairs']} scenarios={len(report['scenarios'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
