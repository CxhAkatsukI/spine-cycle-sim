#!/usr/bin/env python3
"""Freeze K4-shared and Connected Components publication profiles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURES = ROOT / "configs/architectures"
CATALOG_V5 = ROOT / "configs/contracts/grasu_regraph_runtime_packed_capabilities_v5.json"
CATALOG_V6 = ROOT / "configs/contracts/grasu_regraph_publication_capabilities_v6.json"
SIMULATOR_SOURCE_REVISION = "98e032551d9331f30fd2ee92925fff86c89dc021"

ALGORITHMS = {
    "weighted_sssp": "weighted",
    "full_pagerank": "pagerank",
    "thresholded_residual_pagerank": "residual",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clone(payload: Any) -> Any:
    return json.loads(json.dumps(payload))


def dump(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )


def shared_profile(algorithm: str, suffix: str) -> tuple[Path, dict[str, Any]]:
    source = (
        ARCHITECTURES
        / f"grasu_regraph_candidate10_k4_multipart_{suffix}_packed_v5.json"
    )
    profile = json.loads(source.read_text(encoding="ascii"))
    profile_id = (
        f"grasu_regraph_candidate10_k4_shared_multipart_{suffix}_packed_v6"
    )
    profile["profile_id"] = profile_id
    profile["status"] = "projected"
    profile["evidence_tier"] = "simulation_only"
    parameters = profile["parameters"]
    parameters.update(
        {
            "matching_hls_status": "shared_downstream_integrated_top_not_synthesized",
            "pipeline_selection_scope": "publication_primary_k4_shared_downstream",
            "regraph_partition_execution": (
                "finite_work_conserving_parallel_k4_shared_downstream"
            ),
            "regraph_downstream_sharing": "shared",
            "regraph_little_merger_cus": 1,
            "regraph_apply_cus": 1,
            "regraph_hbm_wrapper_cus": 1,
        }
    )
    profile["features"] = list(
        dict.fromkeys(
            [
                *profile["features"],
                "four_parallel_partition_frontends",
                "single_shared_merger_apply_hbm_downstream",
                "finite_shared_downstream_backpressure",
            ]
        )
    )
    profile["limitations"] = [
        (
            "K=4 shared is the primary multi-partition simulator comparator: four "
            "partition frontends serialize through one merger/apply/HBM downstream."
        ),
        (
            "The shared integrated top is not synthesized; performance and resource "
            "counts remain simulation-only until matching HLS is compiled."
        ),
        *[
            value
            for value in profile["limitations"]
            if "K=4 is a simulator scalability point" not in value
        ],
    ]
    target = ARCHITECTURES / f"{profile_id}.json"
    return target, profile


def cc_profile(
    source_path: Path,
    *,
    shared: bool,
) -> tuple[Path, dict[str, Any]]:
    profile = json.loads(source_path.read_text(encoding="ascii"))
    pipelines = int(profile["parameters"]["regraph_compute_pipelines"])
    shared_tag = "_shared" if shared else ""
    profile_id = (
        f"grasu_regraph_candidate10_k{pipelines}{shared_tag}_multipart_cc_packed_v6"
    )
    profile["profile_id"] = profile_id
    profile["status"] = "stable" if pipelines == 1 else "projected"
    profile["evidence_tier"] = "simulation_only"
    profile["source"] = {
        "repository": "git@github.com:CxhAkatsukI/spine-cycle-sim.git",
        "revision": SIMULATOR_SOURCE_REVISION,
        "branch": "codex/simulator-throughput-r19",
        "dirty": False,
    }
    parameters = profile["parameters"]
    for key in (
        "grasu_weight_change_lowering",
        "hls_compute_schedule",
        "hls_compute_units",
        "hls_foundation_profile",
        "hls_foundation_profile_sha256",
        "hls_validation_supersteps",
        "normalized_sssp_superstep_policy",
    ):
        parameters.pop(key, None)
    parameters.update(
        {
            "algorithm_kind": "connected_components",
            "clock_claim": "common_150mhz_projected_from_resource_foundation",
            "connected_components_contract": (
                "weakly_connected_min_vertex_reciprocal_v1"
            ),
            "connected_components_deletion_policy": "full_recompute",
            "connected_components_label_type": "uint32_min_external_vertex",
            "connected_components_weight_semantics": (
                "ignored_by_map_reduce_preserved_in_weighted_pma_update_storage"
            ),
            "grasu_host_reorder": "identity_external_vertex_order",
            "grasu_pma_edge_abi": (
                "normalized_weighted_dst19_weight12_keyed_by_local_destination"
            ),
            "grasu_pma_reservation_key": "local_destination",
            "matching_hls_status": "cc_map_reduce_not_synthesized_simulator_only",
            "normalization_policy": (
                "shared_platform_routed_resource_foundation_simulated_cc_map_reduce"
            ),
            "pipeline_selection_scope": "publication_four_algorithm_profile",
            "regraph_state_bytes_per_vertex": 4,
            "resource_foundation_profile": source_path.stem,
            "regraph_downstream_sharing": "shared" if shared else "direct",
        }
    )
    profile["features"] = [
        value
        for value in profile["features"]
        if value
        not in {
            "hls_derived_full_word_pma",
            "whole_system_sw_emu_correctness",
            "weighted_full_word_pma_update",
            "weight_change_delete_insert_lowering",
            "physical_update_density_vertex_reorder",
            "eight_lane_regraph_little_gs",
            "fixed_host_supersteps",
            "independent_cpu_sssp_oracle",
            "routed_k1_complete_compute_worker",
            "conversion_free_weighted_pma_axis_handoff",
        }
    ]
    profile["features"] = list(
        dict.fromkeys(
            [
                *profile["features"],
                "normalized_destination_pma_update",
                "conversion_free_normalized_pma_axis_handoff",
                "connected_components_min_label_map_reduce",
                "reciprocal_update_contract",
                "insertion_warm_start",
                "deletion_full_recompute",
            ]
        )
    )
    profile["limitations"] = [
        (
            "Connected Components Map/Reduce behavior is execution-driven and "
            "dual-oracle validated but does not yet have a matching HLS synthesis."
        ),
        (
            "The GraSU update and ReGraph memory/pipeline resources are inherited "
            "from frozen profiles; CC-specific control/resource deltas are projected."
        ),
        (
            "Only atomic reciprocal updates implement weakly connected components; "
            "one-sided updates are rejected."
        ),
        (
            "Runtime-packed buffers fail closed at physical pseudo-channel capacity; "
            "oversized datasets require an explicitly labeled capacity slice."
        ),
    ]
    target = ARCHITECTURES / f"{profile_id}.json"
    return target, profile


def main() -> int:
    generated: dict[str, tuple[Path, dict[str, Any]]] = {}
    shared: dict[str, tuple[Path, dict[str, Any]]] = {}
    for algorithm, suffix in ALGORITHMS.items():
        target, profile = shared_profile(algorithm, suffix)
        shared[algorithm] = (target, profile)
        generated[str(profile["profile_id"])] = (target, profile)

    cc_sources = (
        (
            ARCHITECTURES
            / "grasu_regraph_candidate10_k1_multipart_weighted_packed_v5.json",
            False,
        ),
        (
            ARCHITECTURES
            / "grasu_regraph_candidate10_k4_multipart_weighted_packed_v5.json",
            False,
        ),
        (shared["weighted_sssp"][0], True),
    )
    for source, is_shared in cc_sources:
        if source in {item[0] for item in shared.values()}:
            payload = next(
                profile for target, profile in shared.values() if target == source
            )
            temporary = source.with_suffix(".generator-input.json")
            dump(temporary, payload)
            try:
                target, profile = cc_profile(temporary, shared=is_shared)
            finally:
                temporary.unlink(missing_ok=True)
            profile["parameters"]["resource_foundation_profile"] = str(
                payload["profile_id"]
            )
        else:
            target, profile = cc_profile(source, shared=is_shared)
        generated[str(profile["profile_id"])] = (target, profile)

    for target, profile in generated.values():
        dump(target, profile)

    catalog = json.loads(CATALOG_V5.read_text(encoding="ascii"))
    catalog["catalog_id"] = "grasu_regraph_publication_capabilities_v6_20260729"
    if "connected_components" not in catalog["algorithms"]:
        catalog["algorithms"].append("connected_components")
    for entry in catalog["profiles"]:
        if "connected_components" not in entry["unsupported_algorithms"]:
            entry["unsupported_algorithms"].append("connected_components")

    direct_entries = {
        entry["profile_id"]: entry for entry in catalog["profiles"]
    }
    for algorithm, suffix in ALGORITHMS.items():
        source_id = (
            f"grasu_regraph_candidate10_k4_multipart_{suffix}_packed_v5"
        )
        target, profile = shared[algorithm]
        entry = clone(direct_entries[source_id])
        entry["profile_id"] = profile["profile_id"]
        entry["profile_path"] = str(target.relative_to(ROOT))
        entry["profile_sha256"] = sha256(target)
        for capability in entry["supported_algorithms"].values():
            capability["claim_class"] = str(capability["claim_class"]).replace(
                "projected_k4", "projected_k4_shared_downstream"
            )
        catalog["profiles"].append(entry)

    for profile_id, (target, profile) in generated.items():
        if not profile_id.endswith("_cc_packed_v6"):
            continue
        pipelines = int(profile["parameters"]["regraph_compute_pipelines"])
        sharing = str(profile["parameters"]["regraph_downstream_sharing"])
        catalog["profiles"].append(
            {
                "profile_id": profile_id,
                "profile_path": str(target.relative_to(ROOT)),
                "profile_sha256": sha256(target),
                "comparison_role": "normalized",
                "handoff": "normalized_pma_to_axis_stream",
                "conversion_cost": "absent",
                "supported_algorithms": {
                    "connected_components": {
                        "implementation_status": "executable",
                        "claim_class": (
                            f"simulation_only_k{pipelines}_{sharing}_runtime_packed_cc"
                        ),
                        "edge_semantics": "reciprocal_unweighted_destination",
                        "update_semantics": (
                            "insertion_warm_start_delete_full_recompute"
                        ),
                        "convergence": "empty_active_frontier_or_round_limit",
                        "evidence_tier": "simulation_only",
                    }
                },
                "unsupported_algorithms": [
                    item
                    for item in catalog["algorithms"]
                    if item != "connected_components"
                ],
            }
        )
    dump(CATALOG_V6, catalog)
    print(f"wrote {len(generated)} profiles and {CATALOG_V6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
