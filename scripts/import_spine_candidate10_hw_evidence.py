#!/usr/bin/env python3
"""Verify and normalize the frozen Spine candidate-10 hardware evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.evidence.candidate10 import import_candidate10_evidence  # noqa: E402


DEFAULT_SOURCE = Path(
    "/data/feiyang/spine-dynamic-graph-builds/"
    "pipeline_dirty_frontier_publication_1e61fc0_20260725/production/"
    "direct_hw_v5_candidate10_150"
)
DEFAULT_PROFILE = (
    ROOT / "configs/architectures/spine_candidate10_one_pass_1e61fc0.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = import_candidate10_evidence(
        args.source_dir, args.out_dir, args.profile
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
