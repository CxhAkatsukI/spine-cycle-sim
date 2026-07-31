#!/usr/bin/env python3
"""Freeze a formal campaign contract for full-graph GraSU + ReGraph runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT / "configs/contracts/large_graph_publication_campaign_fullgraph_v5.json"
)
TARGET = (
    ROOT / "configs/contracts/large_graph_publication_campaign_fullgraph_v6.json"
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
    parser.add_argument("--source-contract", type=Path, default=SOURCE)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=TARGET)
    parser.add_argument(
        "--contract-id",
        default="large_graph_publication_campaign_fullgraph_v6_20260730",
    )
    parser.add_argument(
        "--milestone", default="fullgraph_v10_warm_sssp_native_o3_lto"
    )
    parser.add_argument("--source-revision")
    parser.add_argument("--behavior-transition")
    parser.add_argument("--hls-reference-branch")
    parser.add_argument("--hls-reference-revision")
    parser.add_argument("--hls-reference-symbol")
    parser.add_argument(
        "--prior-contract-reuse",
        help="explicit fail-closed reuse rule for rows from the source contract",
    )
    parser.add_argument("--nonmonotonic-sssp-edge-cap", type=int)
    args = parser.parse_args()
    plugin = args.plugin.resolve()
    if not plugin.is_file():
        raise FileNotFoundError(f"missing SST plugin: {plugin}")

    source_contract = args.source_contract.resolve()
    contract = json.loads(source_contract.read_text(encoding="ascii"))
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
    simulator = dict(baselines.get("simulator_baseline", {}))
    prior_plugin = simulator.get("plugin_sha256")
    plugin_digest = sha256(plugin)
    simulator.update(
        {
            "milestone": args.milestone,
            "plugin_sha256": plugin_digest,
            "measurement_window": {
                "bootstrap": "reported_separately_not_in_dynamic_e2e",
                "positive_weighted_sssp": (
                    "untimed_verified_old_graph_state_then_timed_update_to_convergence"
                ),
            },
        }
    )
    if args.source_revision:
        simulator["source_commit"] = args.source_revision
    if args.behavior_transition:
        simulator["behavior_transition"] = args.behavior_transition
    hls_reference_values = (
        args.hls_reference_branch,
        args.hls_reference_revision,
        args.hls_reference_symbol,
    )
    if any(hls_reference_values):
        if not all(hls_reference_values):
            raise ValueError("all HLS reference fields must be supplied together")
        simulator["hls_reference"] = {
            "branch": args.hls_reference_branch,
            "revision": args.hls_reference_revision,
            "symbol": args.hls_reference_symbol,
        }
    supersedence = simulator.get("result_supersedence")
    if isinstance(supersedence, dict):
        old_hashes = list(supersedence.get("superseded_plugin_sha256", []))
        if isinstance(prior_plugin, str) and prior_plugin not in old_hashes:
            old_hashes.append(prior_plugin)
        supersedence["superseded_plugin_sha256"] = old_hashes
        supersedence["superseding_plugin_sha256"] = plugin_digest
    baselines["simulator_baseline"] = simulator
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
    weighted = contract["workload_semantics"]["weighted_sssp"]
    weighted.update(
        {
            "primary_source_cohort": "median_degree",
            "source_cohort_roles": {
                "high_degree": "stress_only",
                "median_degree": "headline_primary",
                "random_reachable": "sensitivity_holdout",
            },
            "positive_insertion_measurement_window": "dynamic_e2e_to_convergence",
        }
    )
    contract["claim_boundary"]["weighted_sssp_bootstrap"] = (
        "reported_separately_and_excluded_from_dynamic_e2e"
    )
    if args.prior_contract_reuse:
        contract["claim_boundary"]["prior_contract_reuse"] = (
            args.prior_contract_reuse
        )
    contract["provenance"] = {
        "source_contract": str(source_contract.relative_to(ROOT)),
        "source_contract_sha256": sha256(source_contract),
    }
    args.output.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(args.output)
    print(f"plugin_sha256={sha256(plugin)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
