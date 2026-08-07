#!/usr/bin/env python3
"""Generate immutable simulator profiles for the routed sharded-K4 HLS tops."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "configs" / "architectures"
CONTRACTS = ROOT / "configs" / "contracts"
EVIDENCE = ROOT / "configs" / "evidence" / "grasu_regraph_sharded_k4_hls_route_v1.json"

SPECS = {
    "weighted_sssp": {
        "source": "grasu_regraph_candidate10_k4_shared_multipart_weighted_fullgraph_v7.json",
        "output": "grasu_regraph_sharded_k4_weighted_hls_v8.json",
        "profile_id": "grasu_regraph_sharded_k4_weighted_hls_v8",
        "handoff": "weighted_pma_to_axis_stream",
        "edge_semantics": "weighted32_local_dst19_weight12",
        "update_semantics": "resident_full_word_delete_insert_and_weight_change",
        "convergence": "host_relaunch_until_active_frontier_empty",
        "supported": ("weighted_sssp", "weighted_dynamic_sssp"),
    },
    "connected_components": {
        "source": "grasu_regraph_candidate10_k4_shared_multipart_cc_fullgraph_v7.json",
        "output": "grasu_regraph_sharded_k4_cc_hls_v8.json",
        "profile_id": "grasu_regraph_sharded_k4_cc_hls_v8",
        "handoff": "weighted_pma_to_axis_stream",
        "edge_semantics": "reciprocal_unweighted_local_dst19",
        "update_semantics": "resident_insertion_repair_and_deletion_full_recompute",
        "convergence": "host_relaunch_until_active_frontier_empty",
        "supported": ("connected_components",),
    },
    "thresholded_residual_pagerank": {
        "source": "grasu_regraph_candidate10_k4_shared_multipart_residual_fullgraph_v7.json",
        "output": "grasu_regraph_sharded_k4_residual_hls_v8.json",
        "profile_id": "grasu_regraph_sharded_k4_residual_hls_v8",
        "handoff": "weighted_pma_to_axis_stream",
        "edge_semantics": "weighted32_local_dst19_destination_projection",
        "update_semantics": "resident_degree_correction_then_signed_residual_push",
        "convergence": "direct_per_vertex_residual_threshold_or_iteration_limit",
        "supported": ("thresholded_residual_pagerank",),
    },
}

ALGORITHMS = (
    "unit_weight_sssp",
    "weighted_sssp",
    "weighted_dynamic_sssp",
    "full_pagerank",
    "thresholded_residual_pagerank",
    "connected_components",
)

STALE_PARAMETERS = {
    "foundation_profile",
    "grasu_interleaved_hbm_bytes",
    "grasu_interleaved_hbm_channels",
    "grasu_interleaved_hbm_first_channel",
    "grasu_partition_address_alignment_bytes",
    "grasu_partition_address_arena_base_bytes",
    "grasu_revision",
    "hls_equivalent_compute_units_unsynthesized",
    "hls_foundation_compute_units",
    "hls_foundation_profile",
    "hls_foundation_profile_sha256",
    "normalized_sssp_superstep_policy",
    "physical_address_map_id",
    "pipeline_build_contract_revision",
    "pipeline_freeze_contract",
    "pipeline_freeze_contract_sha256",
    "resource_foundation_profile",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("ascii")


def profile_payload(
    algorithm: str, spec: dict[str, Any], route: dict[str, Any], evidence_sha: str
) -> dict[str, Any]:
    payload = json.loads((ARCH / spec["source"]).read_text(encoding="utf-8"))
    implementation = route["implementations"][algorithm]
    payload["profile_id"] = spec["profile_id"]
    payload["status"] = "stable"
    payload["evidence_tier"] = "hardware_validated"
    payload["source"] = {
        "repository": "/home/chuxiao/grasu-regraph-integration",
        "revision": implementation["source_revision"],
        "branch": "codex/sharded-k4-fullgraph-hls",
        "dirty": False,
    }
    payload["clocks"] = [
        {"name": "kernel", "requested_mhz": 150.0, "achieved_mhz": 150.0},
        {
            "name": "hbm",
            "requested_mhz": 450.0,
            "achieved_mhz": implementation["achieved_hbm_mhz"],
        },
    ]
    payload["evidence"] = [
        {
            "kind": "routed_sharded_k4_hls_manifest",
            "path": str(EVIDENCE.relative_to(ROOT)),
            "sha256": evidence_sha,
        }
    ]
    payload["features"] = [
        "routed_destination_sharded_k4_hls",
        "local_dst19_per_destination_partition",
        "capacity_checked_23_pseudo_channel_placement",
        "four_modulo_assigned_work_conserving_frontends",
        "one_shared_merger_apply_hbm_downstream",
        "conversion_free_weighted_pma_axis_handoff",
        "execution_driven_finite_fifo_axi_hbm_simulation",
        "resident_state_host_relaunch",
        "dual_oracle_correctness_gate",
    ]
    if algorithm == "connected_components":
        payload["features"].extend(
            ["connected_components_min_label_map_reduce", "reciprocal_update_contract"]
        )
    elif algorithm == "thresholded_residual_pagerank":
        payload["features"].extend(
            [
                "split_rank_residual_hbm_state",
                "first_round_rank_degree_correction",
                "signed_residual_push",
                "explicit_hbm_degree_reads",
            ]
        )
    else:
        payload["features"].append("weighted_sssp_min_plus_map_reduce")
    payload["limitations"] = [
        "The simulator serializes four logical downstream objects to model the one routed shared downstream; it does not yet instantiate one literal downstream object.",
        "Per-partition simulator launch and drain bookkeeping is not yet reconciled to the routed top's global round boundary.",
        "The routed xclbin validates implementation feasibility and FPGA timing; simulator cycle claims still require workload-level trend reconciliation.",
    ]
    params = payload["parameters"]
    for key in STALE_PARAMETERS:
        params.pop(key, None)
    params.update(
        {
            "clock_claim": "routed_user_kernel_150mhz",
            "comparison_role": "hardware_native",
            "conversion_cost_included": False,
            "grasu_channel_allocation_policy": "largest_first_lane_aware_0_6_12_18_23",
            "grasu_partition_address_layout": "destination_sharded_local_dst19_v1",
            "grasu_physical_hbm_channels": 32,
            "grasu_pma_hbm_channels": 23,
            "grasu_pma_hbm_first_channel": 0,
            "grasu_runtime_channel_capacity_bytes": 536870912,
            "grasu_sharded_runtime_placement": True,
            "hbm_pseudo_channels_budget": 23,
            "hls_route_tns_ns": implementation["route_tns_ns"],
            "hls_route_wns_ns": implementation["route_wns_ns"],
            "hls_xclbin_bytes": implementation["xclbin_bytes"],
            "hls_xclbin_sha256": implementation["xclbin_sha256"],
            "matching_hls_status": "routed_destination_sharded_k4_shared",
            "max_destination_partitions_without_address_remap": 255,
            "normalization_policy": "none_hardware_native",
            "pipeline_selection_scope": "routed_sharded_k4_shared_downstream",
            "regraph_apply_cus": 1,
            "regraph_compute_pipelines": 4,
            "regraph_destination_partitions": 255,
            "regraph_downstream_sharing": "shared",
            "regraph_hbm_wrapper_cus": 1,
            "regraph_little_gs_cus": 4,
            "regraph_little_merger_cus": 1,
            "regraph_partition_execution": "partition_modulo_4_work_conserving_frontends_one_shared_downstream",
            "regraph_partition_vertices": 65536,
            "regraph_pma_adapter_cus": 4,
            "regraph_source_state_channel": 23,
            "regraph_source_state_mirror_channel": 24,
        }
    )
    if algorithm in {"weighted_sssp", "connected_components"}:
        params.update(
            {
                "regraph_apply_state_channel": 30,
                "regraph_degree_channel": 30,
                "regraph_split_pagerank_state": False,
            }
        )
        params.pop("regraph_residual_state_channel", None)
    else:
        params.update(
            {
                "pagerank_activation_rule": "abs_residual_gt_epsilon",
                "pagerank_residual_contract": "grasu_hardware_warm_dangling_linf",
                "pagerank_state_bytes_per_vertex": 8,
                "pagerank_state_layout": "split_float32_rank_hbm25_residual_hbm26",
                "regraph_apply_state_channel": 25,
                "regraph_degree_channel": 27,
                "regraph_residual_state_channel": 26,
                "regraph_split_pagerank_state": True,
            }
        )
    return payload


def catalog_payload(profiles: dict[str, tuple[dict[str, Any], str]]) -> dict[str, Any]:
    entries = []
    for algorithm, spec in SPECS.items():
        payload, digest = profiles[algorithm]
        supported = {}
        for name in spec["supported"]:
            supported[name] = {
                "implementation_status": "executable",
                "claim_class": "routed_hls_aligned_simulation_pending_cycle_reconciliation",
                "edge_semantics": spec["edge_semantics"],
                "update_semantics": spec["update_semantics"],
                "convergence": spec["convergence"],
                "evidence_tier": "hardware_validated",
            }
        entries.append(
            {
                "profile_id": payload["profile_id"],
                "profile_path": f"configs/architectures/{spec['output']}",
                "profile_sha256": digest,
                "comparison_role": "hardware_native",
                "handoff": spec["handoff"],
                "conversion_cost": "absent",
                "supported_algorithms": supported,
                "unsupported_algorithms": [
                    name for name in ALGORITHMS if name not in supported
                ],
            }
        )
    return {
        "schema_version": 1,
        "catalog_id": "grasu_regraph_sharded_k4_hls_capabilities_v8_20260807",
        "algorithms": list(ALGORITHMS),
        "profiles": entries,
    }


def emit(path: Path, content: bytes, *, check: bool) -> None:
    if check:
        if not path.is_file() or path.read_bytes() != content:
            raise SystemExit(f"stale generated artifact: {path.relative_to(ROOT)}")
        return
    path.write_bytes(content)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    route = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence_sha = sha256(EVIDENCE)
    generated: dict[str, tuple[dict[str, Any], str]] = {}
    for algorithm, spec in SPECS.items():
        payload = profile_payload(algorithm, spec, route, evidence_sha)
        content = dump(payload)
        path = ARCH / spec["output"]
        emit(path, content, check=args.check)
        generated[algorithm] = (payload, hashlib.sha256(content).hexdigest())
    emit(
        CONTRACTS / "grasu_regraph_sharded_k4_hls_capabilities_v8.json",
        dump(catalog_payload(generated)),
        check=args.check,
    )


if __name__ == "__main__":
    main()
