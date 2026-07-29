#!/usr/bin/env python3
"""Audit the frozen large-graph campaign and its source archives."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments import (  # noqa: E402
    DEFAULT_LARGE_GRAPH_CAMPAIGN_CONTRACT,
    load_large_graph_campaign_contract,
    planned_system_runs,
    verify_large_graph_sources,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract", type=Path, default=DEFAULT_LARGE_GRAPH_CAMPAIGN_CONTRACT
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("/data/feiyang/Graph_Datasets"),
    )
    parser.add_argument("--rehash", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    contract = load_large_graph_campaign_contract(args.contract)
    sources = verify_large_graph_sources(
        contract, args.dataset_root, rehash=args.rehash
    )
    payload = {
        "schema_version": 1,
        "contract_id": contract["contract_id"],
        "contract_path": str(args.contract.resolve()),
        "dataset_root": str(args.dataset_root.resolve()),
        "rehash": args.rehash,
        "source_status": [
            {
                "dataset_id": row.dataset_id,
                "path": str(row.path),
                "expected_size": row.expected_size,
                "actual_size": row.actual_size,
                "expected_sha256": row.expected_sha256,
                "actual_sha256": row.actual_sha256,
                "status": row.status,
            }
            for row in sources
        ],
        "planned_system_runs_before_deduplication": planned_system_runs(contract),
        "all_sources_pass": all(row.status == "ok" for row in sources),
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="ascii")
    print(rendered, end="")
    return 0 if payload["all_sources_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
