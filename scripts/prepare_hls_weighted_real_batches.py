#!/usr/bin/env python3
"""Generate or verify common real compact weighted-SSSP small batches."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.real_small_batches import (  # noqa: E402
    build_real_small_batch_manifest,
    validate_real_small_batch_manifest,
)


DEFAULT_SHARED_MANIFEST = (
    ROOT / "configs" / "experiments" / "shared_comparison_workloads_20260725.json"
)
DEFAULT_OUTPUT_DIR = ROOT / "tests" / "data" / "hls_weighted_real_batches"
DEFAULT_MANIFEST = (
    ROOT / "configs" / "experiments" / "hls_weighted_real_small_batches_20260726.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shared-manifest", type=Path, default=DEFAULT_SHARED_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not args.verify_only:
        build_real_small_batch_manifest(
            ROOT,
            shared_manifest_path=args.shared_manifest,
            output_dir=args.output_dir,
            manifest_path=args.manifest,
        )
    manifest = validate_real_small_batch_manifest(ROOT, args.manifest)
    print(
        "PASS weighted-HLS real small-batch corpus: "
        f"runs={len(manifest['runs'])} datasets=3 scenarios=3"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
