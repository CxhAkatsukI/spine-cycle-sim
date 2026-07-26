#!/usr/bin/env python3
"""Generate or verify the paired Full PageRank dense-batch sweep."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.dense_batch_sweep import (  # noqa: E402
    build_dense_batch_manifest,
    validate_dense_batch_manifest,
)


DEFAULT_OUTPUT = ROOT / "tests/data/hls_full_pagerank_dense_batches"
DEFAULT_MANIFEST = (
    ROOT / "configs/experiments/hls_full_pagerank_dense_batch_sweep_20260726.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not args.verify_only:
        build_dense_batch_manifest(
            ROOT, output_dir=args.output_dir, manifest_path=args.manifest
        )
    manifest = validate_dense_batch_manifest(ROOT, args.manifest)
    print(
        "PASS Full PageRank dense batch inputs: "
        f"runs={len(manifest['runs'])} manifest={args.manifest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
