#!/usr/bin/env python3
"""Generate the machine-checked Candidate10 normalized-v3 architecture freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "configs" / "architectures"
CONTRACT_DIR = ROOT / "configs" / "contracts"
EXPERIMENT_DIR = ROOT / "configs" / "experiments"
OUTPUT = CONTRACT_DIR / "candidate10_normalized_architecture_freeze_v3.json"

SPINE_PROFILE = PROFILE_DIR / "spine_candidate10_normalized_v1.json"
GRASU_PROFILES = {
    "weighted_sssp": (
        PROFILE_DIR / "grasu_regraph_candidate10_normalized_hls_weighted_v3.json"
    ),
    "full_pagerank": (
        PROFILE_DIR / "grasu_regraph_candidate10_normalized_hls_pagerank_v3.json"
    ),
    "thresholded_residual_pagerank": (
        PROFILE_DIR
        / "grasu_regraph_candidate10_normalized_hls_residual_pagerank_v3.json"
    ),
}
MATRIX = (
    EXPERIMENT_DIR / "shared_comparison_candidate10_hls_v3_20260726.json"
)

HLS_REVISION = "6378d9e8fa4f8a7a2542ee443d2a3622024bee54"
HLS_SOURCE_HASHES = {
    "scripts/prepare_pagerank_pipeline_build.sh": (
        "1540235e0452af865039ba391e23f28ed0ba50750b021c871e2ca02c45013836"
    ),
    "kernels/grasu_dispatch_degree/grasu_dispatch_degree.cpp": (
        "e0392187797b3cad16e7600e682332fc18624d890dca5075341921a8eb70aa66"
    ),
    "kernels/grasu_degree_update/grasu_degree_update.cpp": (
        "5b8172883c871e621b31ba285ebd50e9a23327568952084dbb777895cba44bca"
    ),
    "kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp": (
        "06f0290d44a9c51d3fdcaaab981d731db5c7f9d07ae94199a93724a2188c8061"
    ),
    "kernels/regraph_stream_little_gs/little_gs_stream.cpp": (
        "aa7e8df97bb1e933fc860ca51d4547b7e301da48b9a37d82cef245df310fd2a8"
    ),
    "kernels/regraph_pagerank_apply/regraph_pagerank_apply.cpp": (
        "35cb0e68a5641d73f3b13ce1c1edd2727787739a09381bdc0fda4b412aa16a9c"
    ),
    "kernels/regraph_pagerank_source_prepare/regraph_pagerank_source_prepare.cpp": (
        "8345d50e332d3cfd4d4e8ffb6ca1010f26df9ffb2f30a8793384cbf2dc118c77"
    ),
    "include/grasu_degree_delta.hpp": (
        "e78b4349c7eff14738cdaef5c031fa8a92b40f38260711fb96b9ca0f42e05578"
    ),
    "include/regraph_pagerank_apply.hpp": (
        "6b3d5c0362a739da83c9ddb6b9b706df2c5402c5c9c4a22b979c21bd31877784"
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="ascii"))


def artifact(path: Path) -> dict[str, str]:
    value = load(path)
    result = {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha256(path),
    }
    if "profile_id" in value:
        result["profile_id"] = value["profile_id"]
    return result


def encode(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")


def normalized_modules(profile: dict[str, Any]) -> dict[str, Any]:
    p = profile["parameters"]
    return {
        "grasu": {
            "bin_search_cus": p["grasu_bin_search_cus"],
            "dispatch_cus": p["grasu_dispatch_cus"],
            "process_cache_cus": p["grasu_process_cache_cus"],
            "process_ddr_cus": p["grasu_process_ddr_cus"],
            "degree_update_cus": p.get("degree_update_rmw_cus", 0),
            "degree_input_fifos": 4 if p.get("degree_update_rmw_cus", 0) else 0,
            "degree_fifo_depth": p.get("grasu_degree_fifo_depth", 0),
            "degree_reorder_entries": p.get("grasu_degree_reorder_entries", 0),
        },
        "conversion_free_handoff": {
            "adapter_cus": p["regraph_pma_adapter_cus"],
            "edge_lanes": p["regraph_pma_adapter_edge_lanes"],
            "axis_fifo_depth": p["regraph_pma_adapter_axis_fifo_depth"],
            "materialized_edge_array": False,
        },
        "regraph": {
            "little_gs_cus": p["regraph_little_gs_cus"],
            "little_merger_cus": p["regraph_little_merger_cus"],
            "hbm_wrapper_cus": p["regraph_hbm_wrapper_cus"],
            "apply_cus": p["regraph_apply_cus"],
            "map_reduce_lanes": p["regraph_map_reduce_lanes"],
            "source_cache_request_fifo_depth": p[
                "regraph_source_cache_request_fifo_depth"
            ],
            "source_cache_response_fifo_depth": p[
                "regraph_source_cache_response_fifo_depth"
            ],
            "gather_merger_fifo_depth": p["regraph_gather_merger_fifo_depth"],
            "merger_apply_fifo_depth": p["regraph_merger_apply_fifo_depth"],
            "apply_wrapper_fifo_depth": p["regraph_apply_wrapper_fifo_depth"],
        },
    }


def build_contract() -> dict[str, Any]:
    spine = load(SPINE_PROFILE)
    grasu = {algorithm: load(path) for algorithm, path in GRASU_PROFILES.items()}
    reference = grasu["full_pagerank"]
    p = reference["parameters"]
    matrix = load(MATRIX)

    return {
        "schema_version": 1,
        "contract_id": "candidate10_normalized_architecture_freeze_v3_20260726",
        "freeze_status": "frozen_before_full_matrix",
        "freeze_policy": {
            "baseline_mutation": "forbidden_after_formal_matrix_start",
            "allowed_changes": [
                "bug fixes that preserve the frozen parameter hash",
                "new evidence and report status",
                "explicit projected profiles with new profile IDs",
            ],
            "forbidden_changes": [
                "tuning FIFO, lane, AXI, HBM, or clock parameters after results",
                "moving required work outside the measured E2E window",
                "calling a prototype matching HLS while blockers remain",
            ],
        },
        "frozen_artifacts": {
            "spine_profile": artifact(SPINE_PROFILE),
            "grasu_regraph_profiles": {
                algorithm: artifact(path)
                for algorithm, path in GRASU_PROFILES.items()
            },
            "experiment_matrix": {
                **artifact(MATRIX),
                "fixtures": len(matrix["fixtures"]),
                "run_cases": len(matrix["runs"]),
            },
        },
        "shared_platform": {
            "device": "xilinx_u55c_gen3x16_xdma_3_202210_1",
            "kernel_clock_mhz": 150,
            "hbm_clock_mhz": 450,
            "hbm_channels": 32,
            "hbm_channel_capacity_bytes": 536870912,
            "hbm_data_width_bits": 512,
            "max_burst_bytes": 1024,
            "memory_backend": "common_execution_driven_sst_dramsim3",
            "resource_budget_pseudo_channels": 23,
            "architecture_specific_outstanding": {
                "spine": spine["memory"]["max_outstanding_per_port"],
                "grasu_regraph": reference["memory"][
                    "max_outstanding_per_port"
                ],
            },
        },
        "spine": {
            "classification": "normalized_from_existing_candidate10_hls",
            "modules": {
                "partitions": spine["parameters"]["partitions"],
                "hot_shards": spine["parameters"]["hot_shards"],
                "families": spine["parameters"]["families"],
                "levels": spine["parameters"]["levels"],
                "compute_lanes": spine["parameters"]["split_compute_width"],
                "graph_hbm_channels": spine["parameters"]["graph_hbm_channels"],
            },
            "capacities": {
                "vertex_partition_size": spine["parameters"][
                    "vertex_partition_size"
                ],
                "tile_vertices": spine["parameters"]["tile_vertices"],
                "tiny_active_threshold": spine["parameters"][
                    "tiny_active_threshold"
                ],
            },
            "hbm_channels": {
                "graph_levels": "0-15",
                "sorted_edges": spine["parameters"]["sorted_edges_hbm_channel"],
                "vertex_state": spine["parameters"]["vertex_state_hbm_channel"],
                "active_bins": spine["parameters"]["active_bins_hbm_channel"],
                "active_out": spine["parameters"]["active_out_hbm_channel"],
                "metadata": spine["parameters"]["metadata_hbm_channel"],
                "result": spine["parameters"]["result_hbm_channel"],
                "active_bitmap": spine["parameters"][
                    "active_bitmap_hbm_channel"
                ],
            },
        },
        "grasu_regraph_normalized": {
            "classification": "normalized_conversion_free_architecture_truth",
            "modules_by_algorithm": {
                algorithm: normalized_modules(profile)
                for algorithm, profile in grasu.items()
            },
            "hbm_channels": {
                "pma": "0-3",
                "source_state_primary": p["regraph_source_state_channel"],
                "source_state_mirror": p["regraph_source_state_mirror_channel"],
                "apply_state": p["regraph_apply_state_channel"],
                "degree": p["regraph_degree_channel"],
            },
            "dataflow": (
                "GraSU PMA update -> finite AXIS adapter -> ReGraph gather/merge "
                "-> apply -> mirrored source-state HBM"
            ),
        },
        "algorithm_contracts": {
            "weighted_sssp": {
                "map": "saturating source_distance_plus_edge_weight",
                "reduce": "unsigned_min",
                "state": "uint32_distance_with_infinity",
                "active": "new_distance_less_than_old_distance",
                "convergence": "frozen_oracle_minimum_host_fixed_supersteps",
            },
            "full_pagerank": {
                "map": "float32_damping_times_rank_over_out_degree",
                "reduce": "float32_sum",
                "state": "float32_rank",
                "active": "all_vertices_each_iteration",
                "convergence": "exactly_three_host_iterations",
            },
            "thresholded_residual_pagerank": {
                "map": "float32_damping_times_residual_over_out_degree",
                "reduce": "float32_signed_sum",
                "state": "float32_rank_plus_float32_residual",
                "active": "abs_residual_gt_epsilon_over_vertices",
                "convergence": "zero_active_or_256_host_iterations",
            },
        },
        "latest_hls_prototype": {
            "repository": "/home/chuxiao/grasu-regraph-integration",
            "branch": "codex/map-reduce-algorithm-hls",
            "revision": HLS_REVISION,
            "source_sha256": HLS_SOURCE_HASHES,
            "status": "full_and_residual_hw_rebuild_running",
            "common_page_rank_cus": 16,
            "components": {
                "bin_search": 4,
                "dispatch_degree": 1,
                "process_cache": 2,
                "process_ddr": 2,
                "degree_update": 1,
                "pma_to_regraph_adapter": 1,
                "little_gs": 1,
                "little_merger": 1,
                "pagerank_apply": 1,
                "pagerank_source_prepare": 1,
                "hbm_wrapper": 1,
            },
            "axis_depths": {
                "bin_search_to_dispatch": 16,
                "dispatch_to_processors": 16,
                "dispatch_to_degree_update": 64,
                "pma_to_little_gs": 32,
                "little_gs_memory_request_response": 32,
                "little_gs_to_merger": 16,
                "merger_to_apply": 16,
                "apply_to_hbm_wrapper": 16,
            },
            "hbm_channels": {
                "pma": "0-3",
                "rank": 4,
                "residual": 5,
                "degree": 6,
                "stats": 7,
                "source_mirrors": [1, 3],
            },
            "handoff": "pma_native_axis_no_materialized_edge_conversion",
        },
        "prototype_crosswalk": [
            {
                "mechanism": "kernel_clock",
                "normalized": "150 MHz",
                "latest_hls": "150 MHz requested",
                "difference_class": "exact_configuration",
                "performance_sensitive": True,
                "publication_blocker": False,
                "disposition": "absorb csynth achieved clock when available",
            },
            {
                "mechanism": "conversion_free_handoff",
                "normalized": "finite 8-lane PMA-to-AXIS adapter",
                "latest_hls": "finite 8-lane PMA-to-AXIS adapter",
                "difference_class": "structurally_equivalent",
                "performance_sensitive": True,
                "publication_blocker": False,
                "disposition": "retain",
            },
            {
                "mechanism": "degree_completion",
                "normalized": "four depth-16 completion FIFOs plus 4096-entry reorder",
                "latest_hls": "single ordered depth-64 AXIS emitted by dispatch",
                "difference_class": "latest_hls_optimization",
                "performance_sensitive": True,
                "publication_blocker": True,
                "disposition": "model both; normalized result keeps frozen path until explicit projected profile",
            },
            {
                "mechanism": "pagerank_state_layout",
                "normalized": "apply state on HBM[30]; residual packed rank+residual",
                "latest_hls": "rank HBM[4], residual HBM[5], degree HBM[6]",
                "difference_class": "feasibility_prototype_mismatch",
                "performance_sensitive": True,
                "publication_blocker": True,
                "disposition": "add native-prototype profile; do not relabel normalized traffic",
            },
            {
                "mechanism": "source_preparation",
                "normalized": "execution-driven per-source cache refill, degree read, and source-map",
                "latest_hls": "separate full-vertex source-prepare pass writing HBM[1] and HBM[3]",
                "difference_class": "feasibility_prototype_mismatch",
                "performance_sensitive": True,
                "publication_blocker": True,
                "disposition": "add exact prototype mode and compare traffic before promotion",
            },
            {
                "mechanism": "residual_state_storage",
                "normalized": "packed 64-bit rank/residual state transaction",
                "latest_hls": "separate 32-bit rank and residual arrays",
                "difference_class": "feasibility_prototype_mismatch",
                "performance_sensitive": True,
                "publication_blocker": True,
                "disposition": "keep normalized frozen; report prototype PPA separately",
            },
            {
                "mechanism": "host_control",
                "normalized": "fixed PageRank iterations or residual active-count termination",
                "latest_hls": "per-kernel ap_ctrl with host sequencing not yet validated E2E",
                "difference_class": "missing_feasibility_evidence",
                "performance_sensitive": True,
                "publication_blocker": True,
                "disposition": "validate launch/order/drain and measured control scope",
            },
        ],
        "claim_boundary": {
            "allowed_now": [
                "dual-oracle correctness",
                "structural exploratory cycles and traffic",
                "component activity and sensitivity",
            ],
            "blocked_now": [
                "matching-HLS normalized label for PageRank",
                "FPGA-measured label for simulator cycles",
                "iso-resource headline before crosswalk blockers close",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    payload = encode(build_contract())
    if args.write:
        OUTPUT.write_bytes(payload)
    elif not OUTPUT.is_file() or OUTPUT.read_bytes() != payload:
        raise ValueError(f"generated architecture freeze is stale: {OUTPUT}")
    action = "wrote" if args.write else "verified"
    print(f"PASS {action} {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
