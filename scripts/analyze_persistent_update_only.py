#!/usr/bin/env python3
"""Combine persistent update-only host and device evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.persistent_update_only import (
    HostRuntimeModel,
    analyze_persistent_update_pair,
)


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--scenario", default="insert")
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--spine", type=Path, required=True)
    parser.add_argument("--grasu", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--h2d-gbps", type=float, default=12.0)
    parser.add_argument("--launch-sync-us", type=float, default=10.0)
    args = parser.parse_args()

    analysis = analyze_persistent_update_pair(
        dataset_id=args.dataset,
        scenario=args.scenario,
        host=_load(args.host),
        spine_result=_load(args.spine),
        grasu_result=_load(args.grasu),
        runtime=HostRuntimeModel(
            h2d_gbytes_per_second=args.h2d_gbps,
            launch_sync_microseconds_per_batch=args.launch_sync_us,
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(analysis["spine_speedup"], sort_keys=True))


if __name__ == "__main__":
    main()
