#!/usr/bin/env python3
"""Generate the resumable workload-materialization campaign manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.large_graph_campaign import (  # noqa: E402
    build_materialization_campaign_manifest,
    load_large_graph_campaign_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT / "configs/contracts/large_graph_publication_campaign_v1.json",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--include-r19", action="store_true")
    parser.add_argument("--sort-parallel", type=int, default=8)
    parser.add_argument("--sort-memory", default="4G")
    args = parser.parse_args()

    manifest = build_materialization_campaign_manifest(
        load_large_graph_campaign_contract(args.contract),
        output_root=args.output_root,
        python=args.python,
        include_r19=args.include_r19,
        sort_parallel=args.sort_parallel,
        sort_memory=args.sort_memory,
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        json.dumps(
            {"manifest": str(args.manifest.resolve()), "jobs": len(manifest["jobs"])},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
