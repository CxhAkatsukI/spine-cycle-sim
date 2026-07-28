#!/usr/bin/env python3
"""Freeze the routed K=1 multi-partition GraSU+ReGraph comparator profiles."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.grasu_addressing import (  # noqa: E402
    FROZEN_CANDIDATE10_ADDRESS_PARAMETERS,
)
PROFILE_DIR = ROOT / "configs" / "architectures"
CONTRACT_PATH = ROOT / "configs" / "contracts" / "grasu_regraph_k_pipeline_freeze_v1.json"
CATALOG_PATH = (
    ROOT / "configs" / "contracts" / "grasu_regraph_k1_multipart_capabilities_v4.json"
)
FEASIBILITY_PATH = (
    ROOT
    / "configs"
    / "contracts"
    / "candidate10_k1_multipart_hls_feasibility_v3.json"
)
SHARED_MANIFEST_PATH = (
    ROOT
    / "configs"
    / "experiments"
    / "shared_comparison_candidate10_k1_multipart_v4_20260728.json"
)
PPA_PATH = ROOT / "configs" / "evidence" / "candidate10_publication_ppa_v3.json"
HLS_PIPELINE_BUILD_REVISION = "80c50937278a0835aee09b62cb1c61bdc4903d4f"

ALGORITHMS = {
    "weighted_sssp": {
        "source": "grasu_regraph_candidate10_normalized_hls_weighted_v3.json",
        "output": "grasu_regraph_candidate10_k1_multipart_weighted_v4.json",
        "profile_id": "grasu_regraph_candidate10_k1_multipart_weighted_v4",
        "ppa_algorithm": "weighted_sssp",
        "source_revision": "ee1cf7a8972ce24867bdc367fd86679bfdd46e17",
        "base_masters": 30,
        "worker_masters": 8,
    },
    "full_pagerank": {
        "source": "grasu_regraph_candidate10_normalized_hls_pagerank_v3.json",
        "output": "grasu_regraph_candidate10_k1_multipart_pagerank_v4.json",
        "profile_id": "grasu_regraph_candidate10_k1_multipart_pagerank_v4",
        "ppa_algorithm": "full_pagerank",
        "source_revision": "7b922ee24c488b8864f0951dc06275d9d0d54b1c",
        "base_masters": 27,
        "worker_masters": 8,
    },
    "thresholded_residual_pagerank": {
        "source": (
            "grasu_regraph_candidate10_normalized_hls_residual_pagerank_v3.json"
        ),
        "output": "grasu_regraph_candidate10_k1_multipart_residual_v4.json",
        "profile_id": "grasu_regraph_candidate10_k1_multipart_residual_v4",
        "ppa_algorithm": "thresholded_residual_pagerank",
        "source_revision": "4338022fd9a5e8e4bf393595d4c1c59f03d00e81",
        "base_masters": 29,
        "worker_masters": 9,
    },
}

RESOURCE_FIELDS = ("lut", "reg", "bram", "uram", "dsp")
WORKER_COMPONENTS = {
    "weighted_sssp": (
        "pma_to_regraph_adapter_1",
        "lksg_stream_1",
        "kernelLittleGSMerger_1",
        "kernelApply_1",
        "kernelHBMWrapper_1",
    ),
    "full_pagerank": (
        "pma_to_regraph_adapter_1",
        "lksg_stream_1",
        "kernelLittleGSMerger_1",
        "regraph_pagerank_apply_1",
        "kernelHBMWrapper_1",
    ),
    "thresholded_residual_pagerank": (
        "pma_to_regraph_adapter_1",
        "lksg_stream_1",
        "kernelLittleGSMerger_1",
        "regraph_pagerank_apply_1",
        "kernelHBMWrapper_1",
    ),
}
PPA_DIR_NAMES = {
    "weighted_sssp": "grasu_weighted_sssp",
    "full_pagerank": "grasu_full_pagerank",
    "thresholded_residual_pagerank": "grasu_thresholded_residual_pagerank",
}


def encode(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def component_resources(algorithm: str) -> dict[str, int]:
    table = (
        ROOT
        / "docs"
        / "evidence"
        / "candidate10_publication_ppa_v3_20260727"
        / PPA_DIR_NAMES[algorithm]
        / "accelerator_util.tsv"
    )
    rows = list(csv.DictReader(table.open(encoding="utf-8"), delimiter="\t"))
    selected = {
        row["name"]: row
        for row in rows
        if row["name"] in WORKER_COMPONENTS[algorithm] and row["is_cu"] == "yes"
    }
    missing = set(WORKER_COMPONENTS[algorithm]) - set(selected)
    if missing:
        raise ValueError(f"missing routed worker components for {algorithm}: {missing}")
    return {
        field: sum(int(selected[name][field]) for name in WORKER_COMPONENTS[algorithm])
        for field in RESOURCE_FIELDS
    }


def build_contract() -> dict[str, Any]:
    ppa = json.loads(PPA_PATH.read_text(encoding="utf-8"))
    routed = {
        build["algorithm"]: build
        for build in ppa["builds"]
        if build["system"] == "grasu_regraph"
    }
    device_budget = {
        "lut": 1_122_597,
        "reg": 2_252_805,
        "bram": 1_816,
        "uram": 960,
        "dsp": 9_020,
    }
    projections: dict[str, Any] = {}
    for algorithm, spec in ALGORITHMS.items():
        build = routed[spec["ppa_algorithm"]]
        baseline = build["expected"]["resources"]
        worker = component_resources(algorithm)
        candidates = []
        for k in (1, 2, 4):
            resources = {
                field: int(baseline[field]) + (k - 1) * worker[field]
                for field in RESOURCE_FIELDS
            }
            resource_fraction = {
                field: resources[field] / device_budget[field]
                for field in RESOURCE_FIELDS
            }
            masters = int(spec["base_masters"]) + (k - 1) * int(
                spec["worker_masters"]
            )
            candidates.append(
                {
                    "compute_pipelines": k,
                    "resource_projection": resources,
                    "maximum_resource_fraction": max(resource_fraction.values()),
                    "axi_master_instances": masters,
                    "resource_ceiling_passed": max(resource_fraction.values()) <= 0.8,
                    "master_budget_passed": masters <= 33,
                    "hls_evidence": "routed" if k == 1 else "not_synthesized",
                }
            )
        projections[algorithm] = {
            "routed_k1_build_id": build["build_id"],
            "routed_k1_resources": baseline,
            "routed_k1_wns_ns": build["expected"]["wns_ns"],
            "replicated_worker_resources": worker,
            "candidates": candidates,
        }
    return {
        "schema_version": 1,
        "contract_id": "grasu_regraph_k_pipeline_freeze_v1_20260728",
        "selection": {
            "compute_pipelines": 1,
            "destination_partition_capacity": 16,
            "address_validated_partitions": 4,
            "dispatch": "finite_work_conserving",
            "partition_execution": "serial_at_k1",
            "reason": (
                "K=1 is the largest routed configuration. Direct complete-worker "
                "replication exceeds the 33-master HMSS budget at K=2 for every "
                "algorithm; K>1 requires a separately synthesized shared-port top."
            ),
            "frozen_before_holdout": True,
        },
        "platform": {
            "device": "xilinx_u55c_gen3x16_xdma_3_202210_1",
            "kernel_clock_mhz": 150,
            "hbm_pseudo_channel_budget": 23,
            "axi_master_instance_budget": 33,
            "maximum_device_resource_fraction": 0.8,
            "device_user_budget": device_budget,
        },
        "hls_pipeline_build_revision": HLS_PIPELINE_BUILD_REVISION,
        "routed_ppa_manifest": {
            "path": str(PPA_PATH.relative_to(ROOT)),
            "sha256": sha256(PPA_PATH),
        },
        "projection_method": (
            "routed K=1 total plus (K-1) times routed complete compute-worker CUs; "
            "AXI masters counted from compiled XO interface metadata"
        ),
        "projections": projections,
        "claim_boundary": {
            "primary": "routed_k1_multi_partition_execution_driven",
            "k2_k4": "scalability_only_requires_shared_port_hls_before_primary_use",
            "resource_projection_is_not_routed_evidence": True,
        },
    }


def make_profile(
    algorithm: str, spec: dict[str, Any], contract_sha: str
) -> dict[str, Any]:
    profile = json.loads((PROFILE_DIR / spec["source"]).read_text(encoding="utf-8"))
    profile["profile_id"] = spec["profile_id"]
    profile["status"] = "stable"
    profile["evidence_tier"] = "synthesis_only"
    profile["source"] = {
        "repository": "/home/chuxiao/grasu-regraph-integration",
        "revision": spec["source_revision"],
        "branch": "codex/map-reduce-algorithm-hls",
        "dirty": False,
    }
    parameters = profile["parameters"]
    parameters.update(
        {
            "clock_claim": "routed_150mhz_near_closed",
            "matching_hls_status": "routed_k1_worker_host_dispatched_partitions",
            "regraph_compute_pipelines": 1,
            "regraph_destination_partitions": 16,
            "regraph_partition_execution": "finite_work_conserving_serial_k1",
            "max_destination_partitions_without_address_remap": 4,
            "pipeline_selection_scope": "global_three_algorithm_k1",
            "pipeline_freeze_contract": str(CONTRACT_PATH.relative_to(ROOT)),
            "pipeline_freeze_contract_sha256": contract_sha,
            "pipeline_build_contract_revision": HLS_PIPELINE_BUILD_REVISION,
            "physical_address_map_id": "candidate10_hbm_pc_nonalias_v1",
            **FROZEN_CANDIDATE10_ADDRESS_PARAMETERS,
        }
    )
    if algorithm == "thresholded_residual_pagerank":
        parameters["grasu_source_state_buffer_stride_bytes"] = 2 * (1 << 20)
    profile["features"] = list(
        dict.fromkeys(
            [
                *profile["features"],
                "runtime_destination_partitioning",
                "finite_work_conserving_partition_dispatch",
                "routed_k1_complete_compute_worker",
                "physical_hbm_pseudo_channel_nonalias_map",
            ]
        )
    )
    profile["limitations"] = [
        (
            "The primary comparator freezes one routed complete ReGraph worker; "
            "destination partitions are dispatched serially at K=1."
        ),
        (
            "K=2 and K=4 are scalability-only until a shared-port integrated top "
            "is synthesized; direct worker replication exceeds the HMSS master budget."
        ),
        (
            "Multi-partition controller timing is execution-driven simulator logic; "
            "the individual K=1 kernels have routed HLS evidence."
        ),
        (
            "Timing is reported at the common 150 MHz comparison clock; the routed "
            "PageRank builds miss the target by less than 0.14 ns."
        ),
        (
            "The physical buffer map supports at most four destination partitions "
            "inside each 512 MiB HBM pseudo-channel; larger graphs require remapping."
        ),
    ]
    profile["evidence"] = [
        {
            "kind": "routed_ppa_manifest",
            "path": str(PPA_PATH.relative_to(ROOT)),
            "sha256": sha256(PPA_PATH),
        },
        {
            "kind": "pipeline_freeze_contract",
            "path": str(CONTRACT_PATH.relative_to(ROOT)),
            "sha256": contract_sha,
        },
    ]
    return profile


def scalability_identity(algorithm: str, k: int) -> tuple[str, str]:
    suffix = {
        "weighted_sssp": "weighted",
        "full_pagerank": "pagerank",
        "thresholded_residual_pagerank": "residual",
    }[algorithm]
    profile_id = f"grasu_regraph_candidate10_k{k}_multipart_{suffix}_v4"
    return profile_id, f"{profile_id}.json"


def make_scalability_profile(
    algorithm: str, base: dict[str, Any], k: int
) -> dict[str, Any]:
    profile = json.loads(json.dumps(base))
    profile_id, _ = scalability_identity(algorithm, k)
    profile["profile_id"] = profile_id
    profile["status"] = "projected"
    profile["evidence_tier"] = "simulation_only"
    parameters = profile["parameters"]
    parameters.update(
        {
            "matching_hls_status": "shared_port_integration_required",
            "regraph_compute_pipelines": k,
            "regraph_partition_execution": f"finite_work_conserving_parallel_k{k}",
            "pipeline_selection_scope": "scalability_only_not_primary",
            "regraph_pma_adapter_cus": k,
            "regraph_little_gs_cus": k,
            "regraph_little_merger_cus": k,
            "regraph_apply_cus": k,
            "regraph_hbm_wrapper_cus": k,
        }
    )
    profile["features"] = list(
        dict.fromkeys([*profile["features"], f"projected_k{k}_worker_pool"])
    )
    profile["limitations"] = [
        (
            f"K={k} is a simulator scalability point, not the primary comparator; "
            "direct complete-worker replication exceeds the U55C HMSS master budget."
        ),
        (
            "The execution-driven workers share the same finite FIFO/AXI/HBM model, "
            "but publication use requires a synthesized shared-port integrated top."
        ),
    ]
    return profile


def make_catalog(
    profiles: dict[str, dict[str, Any]],
    payloads: dict[str, bytes],
    scalability_payloads: dict[tuple[str, int], bytes],
) -> dict[str, Any]:
    algorithms = [
        "unit_weight_sssp",
        "weighted_sssp",
        "weighted_dynamic_sssp",
        "full_pagerank",
        "thresholded_residual_pagerank",
    ]
    supported = {
        "weighted_sssp": {
            "weighted_sssp": {
                "implementation_status": "executable",
                "claim_class": "routed_k1_multi_partition_structural_simulation",
                "edge_semantics": "weighted32_full_word_compare_dst19_weight12",
                "update_semantics": "full_word_delete_insert_then_fixed_round_recompute",
                "convergence": "host_workload_pinned_minimum_supersteps",
                "evidence_tier": "synthesis_only",
            },
            "weighted_dynamic_sssp": {
                "implementation_status": "executable",
                "claim_class": "routed_k1_multi_partition_structural_simulation",
                "edge_semantics": "weighted32_full_word_compare_dst19_weight12",
                "update_semantics": "weight_change_delete_insert_then_fixed_round_recompute",
                "convergence": "host_workload_pinned_minimum_supersteps",
                "evidence_tier": "synthesis_only",
            },
        },
        "full_pagerank": {
            "full_pagerank": {
                "implementation_status": "executable",
                "claim_class": "routed_k1_multi_partition_structural_simulation",
                "edge_semantics": "full_word_pma_destination_projection",
                "update_semantics": "timed_degree_rmw_then_full_recompute",
                "convergence": "host_fixed_iterations",
                "evidence_tier": "synthesis_only",
            }
        },
        "thresholded_residual_pagerank": {
            "thresholded_residual_pagerank": {
                "implementation_status": "executable",
                "claim_class": "routed_k1_multi_partition_structural_simulation",
                "edge_semantics": "full_word_pma_destination_projection",
                "update_semantics": "timed_degree_rmw_then_signed_residual_push",
                "convergence": "signed_residual_threshold_or_iteration_limit",
                "evidence_tier": "synthesis_only",
            }
        },
    }
    entries = []
    for algorithm, spec in ALGORITHMS.items():
        profile_supported = supported[algorithm]
        entries.append(
            {
                "profile_id": spec["profile_id"],
                "profile_path": f"configs/architectures/{spec['output']}",
                "profile_sha256": hashlib.sha256(payloads[algorithm]).hexdigest(),
                "comparison_role": "normalized",
                "handoff": "weighted_pma_to_axis_stream",
                "conversion_cost": "absent",
                "supported_algorithms": profile_supported,
                "unsupported_algorithms": [
                    item for item in algorithms if item not in profile_supported
                ],
            }
        )
        for k in (2, 4):
            profile_id, output = scalability_identity(algorithm, k)
            projected_supported = json.loads(json.dumps(profile_supported))
            for capability in projected_supported.values():
                capability["claim_class"] = (
                    f"projected_k{k}_multi_partition_scalability_only"
                )
                capability["evidence_tier"] = "simulation_only"
            entries.append(
                {
                    "profile_id": profile_id,
                    "profile_path": f"configs/architectures/{output}",
                    "profile_sha256": hashlib.sha256(
                        scalability_payloads[(algorithm, k)]
                    ).hexdigest(),
                    "comparison_role": "normalized",
                    "handoff": "weighted_pma_to_axis_stream",
                    "conversion_cost": "absent",
                    "supported_algorithms": projected_supported,
                    "unsupported_algorithms": [
                        item for item in algorithms if item not in projected_supported
                    ],
                }
            )
    return {
        "schema_version": 1,
        "catalog_id": "grasu_regraph_k1_multipart_capabilities_v4_20260728",
        "algorithms": algorithms,
        "profiles": entries,
    }


def profile_artifact(algorithm: str, payloads: dict[str, bytes]) -> dict[str, str]:
    spec = ALGORITHMS[algorithm]
    return {
        "path": f"configs/architectures/{spec['output']}",
        "profile_id": spec["profile_id"],
        "sha256": hashlib.sha256(payloads[algorithm]).hexdigest(),
    }


def make_feasibility(payloads: dict[str, bytes]) -> dict[str, Any]:
    spine = ROOT / "configs" / "architectures" / "spine_candidate10_normalized_v1.json"
    parent = (
        ROOT
        / "configs"
        / "architectures"
        / "spine_candidate10_one_pass_1e61fc0.json"
    )
    algorithm_entries = {}
    for algorithm in ALGORITHMS:
        artifact = profile_artifact(algorithm, payloads)
        algorithm_entries[algorithm] = {
            "normalized_profile": artifact,
            "closest_hls_profile": artifact,
            "functional_evidence_status": (
                "isolated_hls_csim_and_execution_driven_dual_oracle_pass"
            ),
            "whole_system_hls_status": (
                "routed_k1_near_150mhz_negative_slack_timing_reported"
            ),
            "matching_hls": True,
            "parameter_crosswalk": [],
            "missing_gates": [],
        }
    return {
        "schema_version": 1,
        "contract_id": "candidate10_k1_multipart_hls_feasibility_v3_20260728",
        "claim_class": "routed_k1_multi_partition_execution_driven_simulation",
        "shared_platform_status": "pass",
        "spine": {
            "normalized_profile": {
                "path": str(spine.relative_to(ROOT)),
                "profile_id": "spine_candidate10_normalized_v1",
                "sha256": sha256(spine),
            },
            "native_parent_profile": {
                "path": str(parent.relative_to(ROOT)),
                "profile_id": "spine_candidate10_one_pass_1e61fc0",
                "sha256": sha256(parent),
            },
            "equivalence_status": "normalized_profile_preserves_routed_native_core",
            "matching_hls": True,
            "evidence_status": "routed_xclbin_and_execution_driven_model",
        },
        "algorithms": algorithm_entries,
        "evidence": {
            "path": str(PPA_PATH.relative_to(ROOT)),
            "sha256": sha256(PPA_PATH),
        },
        "claim_gates": {
            "correctness": {
                "eligible": True,
                "label": "dual_oracle_correctness_gated",
                "reason": "Every performance row must pass both independent oracles.",
            },
            "structural_exploratory": {
                "eligible": True,
                "label": "routed_k1_multi_partition_structural",
                "reason": "Both systems use routed HLS anchors and a shared memory model.",
            },
            "headline_normalized_performance": {
                "eligible": True,
                "label": "routed_k1_normalized_simulator_performance",
                "reason": (
                    "K=1 is frozen from routed evidence; multi-partition control is "
                    "execution-driven and all rows remain correctness gated."
                ),
            },
            "iso_resource_performance": {
                "eligible": False,
                "label": "same_platform_resource_reported_not_iso_resource",
                "reason": (
                    "Both systems report routed resources on the same U55C, but "
                    "their LUT, memory, DSP, and AXI-master allocations are not equal."
                ),
            },
            "fpga_measured_performance": {
                "eligible": False,
                "label": "simulator_performance_not_fpga_runtime",
                "reason": "Routed feasibility does not turn simulated cycles into FPGA measurements.",
            },
        },
    }


def update_shared_manifest(
    profile_payloads: dict[str, bytes], catalog_payload: bytes
) -> None:
    manifest = json.loads(SHARED_MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["capability_catalog"]["sha256"] = hashlib.sha256(
        catalog_payload
    ).hexdigest()
    profile_hashes = {
        f"configs/architectures/{ALGORITHMS[algorithm]['output']}": hashlib.sha256(
            payload
        ).hexdigest()
        for algorithm, payload in profile_payloads.items()
    }
    for artifact in manifest["profiles"]:
        if artifact["path"] in profile_hashes:
            artifact["sha256"] = profile_hashes[artifact["path"]]
    manifest["limits"] = {
        "normalized_vertices": 4 * 65_536,
        "not_claimed": "more_than_four_destination_partitions_without_remapping",
        "reason": (
            "The frozen physical HBM map reserves four disjoint 16 MiB windows "
            "per PMA, row, and binary region inside each 512 MiB pseudo-channel."
        ),
    }
    SHARED_MANIFEST_PATH.write_bytes(encode(manifest))


def main() -> int:
    contract = build_contract()
    contract_payload = encode(contract)
    CONTRACT_PATH.write_bytes(contract_payload)
    contract_sha = hashlib.sha256(contract_payload).hexdigest()
    profiles = {
        algorithm: make_profile(algorithm, spec, contract_sha)
        for algorithm, spec in ALGORITHMS.items()
    }
    profile_payloads = {
        algorithm: encode(profile) for algorithm, profile in profiles.items()
    }
    scalability_profiles = {
        (algorithm, k): make_scalability_profile(algorithm, profiles[algorithm], k)
        for algorithm in ALGORITHMS
        for k in (2, 4)
    }
    scalability_payloads = {
        key: encode(profile) for key, profile in scalability_profiles.items()
    }
    for algorithm, spec in ALGORITHMS.items():
        (PROFILE_DIR / spec["output"]).write_bytes(profile_payloads[algorithm])
    for (algorithm, k), payload in scalability_payloads.items():
        _, output = scalability_identity(algorithm, k)
        (PROFILE_DIR / output).write_bytes(payload)
    catalog_payload = encode(
        make_catalog(profiles, profile_payloads, scalability_payloads)
    )
    CATALOG_PATH.write_bytes(catalog_payload)
    FEASIBILITY_PATH.write_bytes(encode(make_feasibility(profile_payloads)))
    update_shared_manifest(profile_payloads, catalog_payload)
    print(f"wrote {CONTRACT_PATH.relative_to(ROOT)} sha256={contract_sha}")
    for algorithm, spec in ALGORITHMS.items():
        print(
            f"wrote configs/architectures/{spec['output']} "
            f"sha256={hashlib.sha256(profile_payloads[algorithm]).hexdigest()}"
        )
        for k in (2, 4):
            profile_id, output = scalability_identity(algorithm, k)
            print(
                f"wrote configs/architectures/{output} "
                f"sha256={hashlib.sha256(scalability_payloads[(algorithm, k)]).hexdigest()} "
                f"profile_id={profile_id}"
            )
    print(f"wrote {CATALOG_PATH.relative_to(ROOT)}")
    print(f"wrote {FEASIBILITY_PATH.relative_to(ROOT)}")
    print(f"updated {SHARED_MANIFEST_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
