#!/usr/bin/env python3
"""Generate the immutable HLS-derived normalized-v3 comparison contracts."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


PROFILE_DIR = ROOT / "configs" / "architectures"
CONTRACT_DIR = ROOT / "configs" / "contracts"
EXPERIMENT_DIR = ROOT / "configs" / "experiments"

SPINE_PROFILE = "spine_candidate10_normalized_v1.json"
SPINE_PARENT = "spine_candidate10_one_pass_1e61fc0.json"
EVIDENCE = ROOT / "docs" / "evidence" / "grasu_regraph_matching_hls_status_20260726.json"

SOURCE_PROFILES = {
    "weighted_sssp": "grasu_regraph_weighted_pma_hls_sw_emu_ff13a67.json",
    "full_pagerank": "grasu_regraph_weighted_pma_hls_proposed_pagerank_ff13a67.json",
    "thresholded_residual_pagerank": (
        "grasu_regraph_weighted_pma_hls_proposed_residual_pagerank_ff13a67.json"
    ),
}
SOURCE_HASHES = {
    "weighted_sssp": "4aa897350dfdd9bddd45ec47654e58edd599050507b3156a77143d9008765f1e",
    "full_pagerank": "53e1688e3f944d59cb2e482f040ed82e4a253e65b0c2e1353103aedb23a9dcda",
    "thresholded_residual_pagerank": (
        "fc86f67e6f9b5c1f8487f1865873bd7a9b9cb26f96f9626cd23e45a7847152c5"
    ),
}
OUTPUT_PROFILES = {
    "weighted_sssp": "grasu_regraph_candidate10_normalized_hls_weighted_v3.json",
    "full_pagerank": "grasu_regraph_candidate10_normalized_hls_pagerank_v3.json",
    "thresholded_residual_pagerank": (
        "grasu_regraph_candidate10_normalized_hls_residual_pagerank_v3.json"
    ),
}
PROFILE_IDS = {key: value.removesuffix(".json") for key, value in OUTPUT_PROFILES.items()}
CATALOG = CONTRACT_DIR / "grasu_regraph_candidate10_hls_capabilities_v3.json"
FEASIBILITY = CONTRACT_DIR / "candidate10_normalized_hls_feasibility_v2.json"
SOURCE_MANIFEST = EXPERIMENT_DIR / "shared_comparison_candidate10_v2_20260726.json"
OUTPUT_MANIFEST = (
    EXPERIMENT_DIR / "shared_comparison_candidate10_hls_v3_20260726.json"
)
PINNED_INPUTS = {
    SOURCE_MANIFEST: "692d6677fc418a77f03dd49e8e16adf9837c1ca6f207903be7d19b0154bc343e",
    PROFILE_DIR / SPINE_PROFILE: (
        "4e31633c55abfdc57fd4537119d6abb6d7a4f0313dcfc81332fa0ed0a6320c0a"
    ),
    PROFILE_DIR / SPINE_PARENT: (
        "a23737c17f6650cea0185bd3eba9d425dbc151f35372d33130464df780312717"
    ),
    EVIDENCE: "9bdf345bf0de580ef6cd8cd5bff2c5c8a49d9351ff84802bd72f9c7dd3a47731",
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def encode(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")


def load_pinned_profile(algorithm: str) -> dict[str, Any]:
    path = PROFILE_DIR / SOURCE_PROFILES[algorithm]
    actual = sha256_file(path)
    if actual != SOURCE_HASHES[algorithm]:
        raise ValueError(
            f"source profile drifted for {algorithm}: expected "
            f"{SOURCE_HASHES[algorithm]}, got {actual}"
        )
    return json.loads(path.read_text(encoding="ascii"))


def validate_pinned_inputs() -> None:
    for path, expected in PINNED_INPUTS.items():
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(
                f"v3 generator input drifted: {path}; expected {expected}, got {actual}"
            )


def normalized_profile(algorithm: str) -> dict[str, Any]:
    source = load_pinned_profile(algorithm)
    profile = deepcopy(source)
    profile["profile_id"] = PROFILE_IDS[algorithm]
    profile["status"] = "experimental"
    profile["evidence_tier"] = "simulation_only"
    profile["evidence"] = []
    for clock in profile["clocks"]:
        if clock["name"] == "kernel":
            clock["requested_mhz"] = 150.0
            clock["achieved_mhz"] = 150.0
    parameters = profile["parameters"]
    parameters.update(
        {
            "comparison_role": "normalized",
            "resource_reference_profile": "spine_candidate10_normalized_v1",
            "hbm_pseudo_channels_budget": 23,
            "normalization_policy": (
                "hls_microarchitecture_preserved_shared_platform_clock_only"
            ),
            "hls_foundation_profile": source["profile_id"],
            "hls_foundation_profile_sha256": SOURCE_HASHES[algorithm],
            "matching_hls_status": "pending",
        }
    )
    if algorithm == "weighted_sssp":
        parameters["normalized_sssp_superstep_policy"] = (
            "oracle_minimum_host_fixed_supersteps"
        )
    if algorithm in {"full_pagerank", "thresholded_residual_pagerank"}:
        if parameters.get("pagerank_degree_update_timing") is not True:
            raise ValueError(f"{algorithm} source profile omits degree timing")
    if parameters.get("regraph_map_reduce_lanes") != 8:
        raise ValueError(f"{algorithm} HLS foundation is not eight-lane")
    if (
        parameters.get("grasu_pma_edge_abi")
        != "regraph_weighted32_full_word_compare_dst19_weight12"
    ):
        raise ValueError(f"{algorithm} HLS foundation lacks full-word ABI")
    if profile["memory"]["max_outstanding_per_port"] != 16:
        raise ValueError(f"{algorithm} HLS foundation outstanding depth drifted")

    profile["features"] = list(
        dict.fromkeys(
            [
                "candidate10_shared_platform_normalized",
                "hls_derived_full_word_pma",
                "eight_lane_regraph_map_reduce",
                *profile["features"],
            ]
        )
    )
    profile["limitations"] = [
        (
            "This immutable v3 profile preserves the closest HLS datapath and "
            "normalizes only the comparison clock/platform contract."
        ),
        (
            "It is execution-driven structural simulation until an exact "
            "whole-system HLS variant satisfies the matching-HLS gate."
        ),
        (
            "The profile supports one 19-bit destination partition; larger "
            "graphs require the separately modeled partitioned extension."
        ),
        *source["limitations"],
    ]
    return profile


def capability_catalog(
    profiles: dict[str, dict[str, Any]], profile_payloads: dict[str, bytes]
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
                "claim_class": "hls_derived_normalized_structural_simulation",
                "edge_semantics": "weighted32_full_word_compare_dst19_weight12",
                "update_semantics": (
                    "full_word_delete_insert_then_oracle_minimum_fixed_round_recompute"
                ),
                "convergence": "host_workload_pinned_minimum_supersteps",
                "evidence_tier": "simulation_only",
            },
            "weighted_dynamic_sssp": {
                "implementation_status": "executable",
                "claim_class": "hls_derived_normalized_structural_simulation",
                "edge_semantics": "weighted32_full_word_compare_dst19_weight12",
                "update_semantics": (
                    "weight_change_delete_old_insert_new_then_minimum_fixed_round_recompute"
                ),
                "convergence": "host_workload_pinned_minimum_supersteps",
                "evidence_tier": "simulation_only",
            },
        },
        "full_pagerank": {
            "full_pagerank": {
                "implementation_status": "executable",
                "claim_class": "hls_derived_normalized_structural_simulation",
                "edge_semantics": "full_word_pma_destination_projection",
                "update_semantics": "timed_degree_rmw_then_full_recompute",
                "convergence": "host_fixed_iterations",
                "evidence_tier": "simulation_only",
            }
        },
        "thresholded_residual_pagerank": {
            "thresholded_residual_pagerank": {
                "implementation_status": "executable",
                "claim_class": "hls_derived_normalized_structural_simulation",
                "edge_semantics": "full_word_pma_destination_projection",
                "update_semantics": "timed_degree_rmw_then_signed_residual_push",
                "convergence": "signed_residual_threshold_or_iteration_limit",
                "evidence_tier": "simulation_only",
            }
        },
    }
    entries = []
    for algorithm in (
        "weighted_sssp",
        "full_pagerank",
        "thresholded_residual_pagerank",
    ):
        profile_supported = supported[algorithm]
        entries.append(
            {
                "profile_id": profiles[algorithm]["profile_id"],
                "profile_path": (
                    f"configs/architectures/{OUTPUT_PROFILES[algorithm]}"
                ),
                "profile_sha256": sha256_bytes(profile_payloads[algorithm]),
                "comparison_role": "normalized",
                "handoff": "weighted_pma_to_axis_stream",
                "conversion_cost": "absent",
                "supported_algorithms": profile_supported,
                "unsupported_algorithms": [
                    item for item in algorithms if item not in profile_supported
                ],
            }
        )
    return {
        "schema_version": 1,
        "catalog_id": "grasu_regraph_candidate10_hls_capabilities_v3_20260726",
        "algorithms": algorithms,
        "profiles": entries,
    }


def profile_artifact(path: str, profile_id: str, payload: bytes) -> dict[str, str]:
    return {
        "path": path,
        "profile_id": profile_id,
        "sha256": sha256_bytes(payload),
    }


def feasibility_contract(
    profiles: dict[str, dict[str, Any]], profile_payloads: dict[str, bytes]
) -> dict[str, Any]:
    algorithms: dict[str, Any] = {}
    statuses = {
        "weighted_sssp": (
            "whole_system_sw_emu_cpu_oracle_pass",
            "routed_global_timing_failed_relink_pending",
            [
                "close the weighted whole-system HBM-clock timing paths",
                "synthesize and archive the exact normalized profile identity",
            ],
        ),
        "full_pagerank": (
            "simulator_dual_oracle_and_isolated_policy_tests_pass",
            "not_implemented",
            [
                (
                    "integrate degree RMW, dangling reduction, policy, state "
                    "storage, and host control"
                ),
                "pass a whole-system HLS correctness oracle",
                "obtain whole-system synthesis resources and timing",
            ],
        ),
        "thresholded_residual_pagerank": (
            "simulator_dual_oracle_and_isolated_policy_tests_pass",
            "not_implemented",
            [
                "integrate degree RMW, residual activation, packed state, and host control",
                "pass a whole-system HLS correctness oracle",
                "obtain whole-system synthesis resources and timing",
            ],
        ),
    }
    for algorithm in profiles:
        functional, whole_system, missing = statuses[algorithm]
        algorithms[algorithm] = {
            "normalized_profile": profile_artifact(
                f"configs/architectures/{OUTPUT_PROFILES[algorithm]}",
                profiles[algorithm]["profile_id"],
                profile_payloads[algorithm],
            ),
            "closest_hls_profile": profile_artifact(
                f"configs/architectures/{SOURCE_PROFILES[algorithm]}",
                load_pinned_profile(algorithm)["profile_id"],
                (PROFILE_DIR / SOURCE_PROFILES[algorithm]).read_bytes(),
            ),
            "functional_evidence_status": functional,
            "whole_system_hls_status": whole_system,
            "matching_hls": False,
            "parameter_crosswalk": [
                {
                    "field": "/clocks/0/requested_mhz",
                    "normalized_value": 150.0,
                    "closest_hls_value": 200.0,
                    "difference_class": "intentional_shared_platform_normalization",
                    "publication_blocker": False,
                    "reason": (
                        "The HLS-derived datapath is preserved; only the shared "
                        "comparison clock is lowered to 150 MHz."
                    ),
                }
            ],
            "missing_gates": missing,
        }
    return {
        "schema_version": 1,
        "contract_id": "candidate10_normalized_hls_feasibility_v2_20260726",
        "claim_class": "hls_derived_normalized_feasibility_gate_not_performance",
        "shared_platform_status": "pass",
        "spine": {
            "normalized_profile": profile_artifact(
                f"configs/architectures/{SPINE_PROFILE}",
                SPINE_PROFILE.removesuffix(".json"),
                (PROFILE_DIR / SPINE_PROFILE).read_bytes(),
            ),
            "native_parent_profile": profile_artifact(
                f"configs/architectures/{SPINE_PARENT}",
                SPINE_PARENT.removesuffix(".json"),
                (PROFILE_DIR / SPINE_PARENT).read_bytes(),
            ),
            "equivalence_status": "candidate10_semantics_preserved_platform_normalized",
            "matching_hls": True,
            "evidence_status": "native_parent_routed_hardware_validated",
        },
        "algorithms": algorithms,
        "evidence": {
            "path": "docs/evidence/grasu_regraph_matching_hls_status_20260726.json",
            "sha256": sha256_file(EVIDENCE),
        },
        "claim_gates": {
            "correctness": {
                "eligible": True,
                "label": "dual_oracle_simulator_correctness_only",
                "reason": "Every reported run must pass both independent oracles.",
            },
            "structural_exploratory": {
                "eligible": True,
                "label": "candidate10_hls_derived_normalized_structural_execution_driven",
                "reason": (
                    "Both models use HLS-derived mechanisms on one platform, but "
                    "three-algorithm matching HLS is incomplete."
                ),
            },
            "headline_normalized_performance": {
                "eligible": False,
                "label": "blocked_missing_symmetric_matching_hls",
                "reason": "All three GraSU/ReGraph algorithms need matching whole-system HLS.",
            },
            "iso_resource_performance": {
                "eligible": False,
                "label": "blocked_missing_exact_resource_crosswalk",
                "reason": "PageRank lacks whole-system resources and timing.",
            },
            "fpga_measured_performance": {
                "eligible": False,
                "label": "blocked_normalized_is_not_measured_hardware",
                "reason": "Normalized simulator output is never native FPGA measurement.",
            },
        },
    }


def upgraded_manifest(
    profile_payloads: dict[str, bytes], catalog_payload: bytes
) -> dict[str, Any]:
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="ascii"))
    manifest["matrix_id"] = "shared_comparison_candidate10_hls_v3_20260726"
    manifest["claim_class"] = "hls_derived_normalized_execution_driven_contract"
    manifest["capability_catalog"] = {
        "path": "configs/contracts/grasu_regraph_candidate10_hls_capabilities_v3.json",
        "sha256": sha256_bytes(catalog_payload),
    }
    manifest["profiles"] = [
        {
            "path": f"configs/architectures/{SPINE_PARENT}",
            "sha256": sha256_file(PROFILE_DIR / SPINE_PARENT),
        },
        {
            "path": f"configs/architectures/{SPINE_PROFILE}",
            "sha256": sha256_file(PROFILE_DIR / SPINE_PROFILE),
        },
        *[
            {
                "path": f"configs/architectures/{OUTPUT_PROFILES[algorithm]}",
                "sha256": sha256_bytes(profile_payloads[algorithm]),
            }
            for algorithm in (
                "weighted_sssp",
                "full_pagerank",
                "thresholded_residual_pagerank",
            )
        ],
    ]
    contract = manifest["comparison_contract"]
    contract["grasu_profile_set"] = "hls_v3"
    contract["grasu_hls_lineage"] = (
        "full-word PMA, eight-lane ReGraph, 16 outstanding requests, and timed "
        "PageRank degree RMW are inherited from the closest HLS profiles"
    )
    contract["sssp_superstep_policy"] = (
        "CPU oracle selects the minimum correct fixed supersteps for GraSU/ReGraph; "
        "oracle execution time is excluded"
    )
    contract["resource_feasibility_gate"] = (
        "HLS-derived v3 removes known v2 parameter mismatches; headline remains "
        "blocked until all three whole-system HLS gates pass"
    )
    fixtures = {fixture["fixture_id"]: fixture for fixture in manifest["fixtures"]}
    for run in manifest["runs"]:
        if run["algorithm"] in {
            "full_pagerank",
            "thresholded_residual_pagerank",
        }:
            run["update"] = fixtures[run["fixture_id"]]["empty_update"]
    return manifest


def write_or_verify(path: Path, payload: bytes, write: bool) -> None:
    if write:
        path.write_bytes(payload)
        return
    if not path.is_file() or path.read_bytes() != payload:
        raise ValueError(f"generated artifact is missing or stale: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    validate_pinned_inputs()
    profiles = {
        algorithm: normalized_profile(algorithm) for algorithm in SOURCE_PROFILES
    }
    profile_payloads = {
        algorithm: encode(profile) for algorithm, profile in profiles.items()
    }
    catalog = capability_catalog(profiles, profile_payloads)
    catalog_payload = encode(catalog)
    feasibility = feasibility_contract(profiles, profile_payloads)
    feasibility_payload = encode(feasibility)
    manifest = upgraded_manifest(profile_payloads, catalog_payload)
    manifest_payload = encode(manifest)

    for algorithm, filename in OUTPUT_PROFILES.items():
        write_or_verify(PROFILE_DIR / filename, profile_payloads[algorithm], args.write)
    write_or_verify(CATALOG, catalog_payload, args.write)
    write_or_verify(FEASIBILITY, feasibility_payload, args.write)
    write_or_verify(OUTPUT_MANIFEST, manifest_payload, args.write)

    action = "wrote" if args.write else "verified"
    print(
        f"PASS {action} HLS-derived normalized v3: profiles=3 "
        f"runs={len(manifest['runs'])} fixtures={len(manifest['fixtures'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
