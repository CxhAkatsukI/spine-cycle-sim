#!/usr/bin/env python3
"""Build or verify the near-paper-scale AskUbuntu simple-graph matrix."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.temporal_real_batches import (  # noqa: E402
    build_askubuntu_paper_scale_manifest,
    validate_askubuntu_paper_scale_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root", type=Path, default=Path("/data/feiyang/Graph_Datasets")
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "tests/data/candidate10_askubuntu_paper_scale",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT
        / "configs/experiments/candidate10_grasu_askubuntu_paper_scale_v1_20260728.json",
    )
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        manifest = validate_askubuntu_paper_scale_manifest(ROOT, args.manifest)
    else:
        manifest = build_askubuntu_paper_scale_manifest(
            ROOT,
            source_root=args.source_root,
            output_dir=args.output_dir,
            manifest_path=args.manifest,
        )
    dataset = manifest["datasets"][0]
    print(
        "PASS AskUbuntu paper-scale corpus: "
        f"vertices={dataset['graph']['vertices']} "
        f"edges={dataset['graph']['records']} runs={len(manifest['runs'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
