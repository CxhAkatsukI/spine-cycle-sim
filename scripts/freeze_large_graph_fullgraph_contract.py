#!/usr/bin/env python3
"""Freeze a formal campaign contract for full-graph GraSU + ReGraph runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/contracts/large_graph_publication_campaign_v1.json"
TARGET = (
    ROOT / "configs/contracts/large_graph_publication_campaign_fullgraph_v2.json"
)
CATALOG = ROOT / "configs/contracts/grasu_regraph_full_graph_capabilities_v7.json"

PROFILE_NAMES = {
    "grasu_regraph_k1": {
        "weighted_sssp": (
            "grasu_regraph_candidate10_k1_multipart_weighted_fullgraph_v7.json"
        ),
        "connected_components": (
            "grasu_regraph_candidate10_k1_multipart_cc_fullgraph_v7.json"
        ),
        "full_pagerank": (
            "grasu_regraph_candidate10_k1_multipart_pagerank_fullgraph_v7.json"
        ),
        "thresholded_residual_pagerank": (
            "grasu_regraph_candidate10_k1_multipart_residual_fullgraph_v7.json"
        ),
    },
    "grasu_regraph_k4_shared": {
        "weighted_sssp": (
            "grasu_regraph_candidate10_k4_shared_multipart_weighted_fullgraph_v7.json"
        ),
        "connected_components": (
            "grasu_regraph_candidate10_k4_shared_multipart_cc_fullgraph_v7.json"
        ),
        "full_pagerank": (
            "grasu_regraph_candidate10_k4_shared_multipart_pagerank_fullgraph_v7.json"
        ),
        "thresholded_residual_pagerank": (
            "grasu_regraph_candidate10_k4_shared_multipart_residual_fullgraph_v7.json"
        ),
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=TARGET)
    parser.add_argument(
        "--contract-id",
        default="large_graph_publication_campaign_fullgraph_v2_20260729",
    )
    parser.add_argument(
        "--milestone", default="fullgraph_v7_interleaved_23pc_native_o3_lto"
    )
    parser.add_argument("--nonmonotonic-sssp-edge-cap", type=int)
    args = parser.parse_args()
    plugin = args.plugin.resolve()
    if not plugin.is_file():
        raise FileNotFoundError(f"missing SST plugin: {plugin}")

    contract = json.loads(SOURCE.read_text(encoding="ascii"))
    contract["contract_id"] = args.contract_id
    baselines = contract["architecture_baselines"]
    for system, algorithms in PROFILE_NAMES.items():
        baseline = baselines[system]
        baseline["addressing"] = (
            "runtime_packed_interleaved_v2_23pc_capacity_checked"
        )
        baseline["implementation_boundary"] = (
            "routed_compute_foundation_plus_simulator_only_full_graph_mapper"
        )
        for algorithm, filename in algorithms.items():
            path = ROOT / "configs/architectures" / filename
            baseline["profiles"][algorithm] = [
                str(path.relative_to(ROOT)),
                sha256(path),
            ]
    baselines["grasu_regraph_capability_catalog"] = {
        "path": str(CATALOG.relative_to(ROOT)),
        "sha256": sha256(CATALOG),
    }
    baselines["simulator_baseline"] = {
        "milestone": args.milestone,
        "plugin_sha256": sha256(plugin),
    }
    contract["claim_boundary"]["grasu_regraph_full_graph_addressing"] = (
        "simulator_only_capacity_checked_23pc_mapper_hls_integration_pending"
    )
    if args.nonmonotonic_sssp_edge_cap is not None:
        if not 0 < args.nonmonotonic_sssp_edge_cap <= 131_072:
            raise ValueError("non-monotonic SSSP edge cap exceeds MAX_SORT_EDGES")
        weighted = contract["workload_semantics"]["weighted_sssp"]
        weighted.update(
            {
                "insertion_graph_scope": "full_directed_graph",
                "nonmonotonic_graph_scope": "bounded_real_topology_hash_slice",
                "nonmonotonic_edge_cap": args.nonmonotonic_sssp_edge_cap,
                "spine_max_sort_edges": 131_072,
                "fallback_reason": (
                    "delete_or_weight_increase_requires_exact_snapshot_rebuild"
                ),
            }
        )
    args.output.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(args.output)
    print(f"plugin_sha256={sha256(plugin)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
