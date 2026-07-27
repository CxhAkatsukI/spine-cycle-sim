#!/usr/bin/env python3
"""Analyze paper-scale opt-v2 Spine versus K=1 GraSU+ReGraph runs."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.temporal_three_algorithm_analysis import (  # noqa: E402
    analyze_opt_v2_k1_paper_scale,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weighted-dir", type=Path, required=True)
    parser.add_argument("--full-pagerank-dir", type=Path, required=True)
    parser.add_argument("--residual-dir", type=Path, required=True)
    parser.add_argument(
        "--input-manifest",
        type=Path,
        default=ROOT
        / "configs/experiments/candidate10_grasu_askubuntu_paper_scale_v1_20260728.json",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--paper-data-dir", type=Path)
    args = parser.parse_args()
    report = analyze_opt_v2_k1_paper_scale(
        matrix_dirs={
            "weighted_sssp": args.weighted_dir,
            "full_pagerank": args.full_pagerank_dir,
            "thresholded_residual_pagerank": args.residual_dir,
        },
        input_manifest_path=args.input_manifest,
        out_dir=args.out_dir,
        paper_data_dir=args.paper_data_dir,
    )
    print(
        "PASS opt-v2/K=1 paper scale: "
        f"pairs={report['pairs']} rows={report['system_rows']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
