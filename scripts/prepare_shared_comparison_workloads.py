#!/usr/bin/env python3
"""Generate or verify the frozen shared Spine/GraSU/ReGraph workload corpus."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments import (  # noqa: E402
    build_shared_comparison_corpus,
    validate_shared_comparison_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("/data/feiyang/AE/AE_Final/datasets"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "tests" / "data" / "shared_comparison",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT
        / "configs"
        / "experiments"
        / "shared_comparison_workloads_20260725.json",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="verify committed artifacts without requiring the raw real datasets",
    )
    args = parser.parse_args()
    if args.verify_only:
        manifest = validate_shared_comparison_manifest(ROOT, args.manifest)
    else:
        manifest = build_shared_comparison_corpus(
            ROOT,
            source_root=args.source_root,
            output_dir=args.output_dir,
            manifest_path=args.manifest,
        )
    counts = manifest["counts"]
    print(
        "PASS shared workload corpus: "
        f"{counts['synthetic_fixtures']} synthetic, "
        f"{counts['real_datasets']} real datasets, "
        f"{counts['run_cases']} run cases"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
