#!/usr/bin/env python3
"""Generate or verify the pinned large real-edge Full PageRank workload."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.large_real_pagerank import (  # noqa: E402
    build_large_real_pagerank_manifest,
    validate_large_real_pagerank_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("/data/feiyang/AE/AE_Final/datasets/amazon-2008.mtx"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "tests/data/hls_full_pagerank_large_real",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=(
            ROOT
            / "configs/experiments/hls_full_pagerank_real_large_runtime_20260726.json"
        ),
    )
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        manifest = validate_large_real_pagerank_manifest(ROOT, args.manifest)
    else:
        manifest = build_large_real_pagerank_manifest(
            ROOT,
            source_path=args.source,
            output_dir=args.output_dir,
            manifest_path=args.manifest,
        )
    run = manifest["runs"][0]
    print(
        f"PASS {manifest['matrix_id']}: vertices={run['graph']['vertices']} "
        f"edges={run['graph']['records']} hot={len(run['hot_vertices'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
