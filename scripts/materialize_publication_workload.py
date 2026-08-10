#!/usr/bin/env python3
"""Materialize one frozen publication graph without Python graph copies."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.large_graph_campaign import (  # noqa: E402
    load_large_graph_campaign_contract,
)
from spine_cycle_sim.experiments.publication_workloads import (  # noqa: E402
    DEFAULT_BATCH_SIZES,
    DEFAULT_PAGERANK_SCALES,
    materialize_publication_workload,
    publication_source_spec,
    r19_source_spec,
)


def _integers(value: str) -> tuple[int, ...]:
    parsed = tuple(int(item) for item in value.split(",") if item)
    if not parsed or any(item <= 0 for item in parsed):
        raise argparse.ArgumentTypeError("expected comma-separated positive integers")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT / "configs/contracts/large_graph_publication_campaign_v1.json",
    )
    parser.add_argument(
        "--dataset-root", type=Path, default=Path("/data/feiyang/Graph_Datasets")
    )
    parser.add_argument(
        "--r19-source",
        type=Path,
        default=Path("/data/feiyang/AE/AE_Final/datasets/rmat-19-32.txt"),
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sort-parallel", type=int, default=8)
    parser.add_argument("--sort-memory", default="4G")
    parser.add_argument(
        "--batch-sizes",
        type=_integers,
        default=DEFAULT_BATCH_SIZES,
    )
    parser.add_argument(
        "--pagerank-scales",
        type=_integers,
        default=DEFAULT_PAGERANK_SCALES,
    )
    parser.add_argument("--progress-path", type=Path)
    parser.add_argument("--keep-intermediates", action="store_true")
    args = parser.parse_args()

    contract = load_large_graph_campaign_contract(args.contract)
    spec = (
        r19_source_spec(args.r19_source, contract)
        if args.dataset == contract["synthetic_endpoint"]["dataset_id"]
        else publication_source_spec(contract, args.dataset, args.dataset_root)
    )
    progress_path = args.progress_path
    if progress_path is None and os.environ.get("SPINE_CAMPAIGN_PROGRESS_PATH"):
        progress_path = Path(os.environ["SPINE_CAMPAIGN_PROGRESS_PATH"])
    manifest = materialize_publication_workload(
        spec,
        args.out_dir,
        sort_parallel=args.sort_parallel,
        sort_memory=args.sort_memory,
        batch_sizes=tuple(args.batch_sizes),
        pagerank_scales=tuple(args.pagerank_scales),
        progress_path=progress_path,
        keep_intermediates=args.keep_intermediates,
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "dataset_id": manifest["dataset_id"],
                "vertices": manifest["graphs"]["directed"]["vertices"],
                "directed_edges": manifest["graphs"]["directed"]["records"],
                "reciprocal_edges": manifest["graphs"]["reciprocal"]["records"],
                "manifest": str((args.out_dir / "materialization_manifest.json").resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
