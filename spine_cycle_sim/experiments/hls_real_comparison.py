"""Contracts for HLS-aligned weighted SSSP real compact comparisons."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping

from .memory_traffic import split_memory_metrics

SPINE_INFINITY = 0xFFFFFFFF
GRASU_HLS_INFINITY = 0x7FFFFFFE


def spine_memory_metrics(
    result: Mapping[str, object],
) -> dict[str, int | float]:
    backend_requests = int(result["backend_requests"])
    cold_requests = int(result["cold_backend_requests"])
    aligned_requests = int(result["update_backend_requests"])
    return split_memory_metrics(
        result,
        first_key="cold_backend_traffic",
        first_prefix="cold_backend",
        second_key="update_backend_traffic",
        second_prefix="aligned_backend",
        backend_requests=backend_requests,
        first_requests=cold_requests,
        second_requests=aligned_requests,
    )


def grasu_memory_metrics(
    result: Mapping[str, object],
) -> dict[str, int | float]:
    return split_memory_metrics(
        result,
        first_key="update_backend_traffic",
        first_prefix="update_backend",
        second_key="compute_backend_traffic",
        second_prefix="compute_backend",
        backend_requests=int(result["backend_requests"]),
        first_requests=int(result["update_backend_requests"]),
        second_requests=int(result["compute_backend_requests"]),
    )


def _memory_metrics_valid(
    result: Mapping[str, object], *, system: str
) -> bool:
    try:
        if system == "spine":
            spine_memory_metrics(result)
        elif system == "grasu_regraph":
            grasu_memory_metrics(result)
        else:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    return True


def expected_spine_update_path(scenario: str) -> str:
    if scenario == "insert":
        return "incremental_relax"
    if scenario in {"delete", "weight_change"}:
        return "full_rebuild"
    raise ValueError(f"unsupported real small-batch scenario: {scenario}")


def normalized_distances(values: object) -> tuple[int | None, ...]:
    if not isinstance(values, list):
        raise ValueError("distance vector is missing")
    normalized: list[int | None] = []
    for raw_value in values:
        value = int(raw_value)
        normalized.append(
            None
            if value in {SPINE_INFINITY, GRASU_HLS_INFINITY}
            else value
        )
    return tuple(normalized)


def distance_vector_sha256(values: tuple[int | None, ...]) -> str:
    return hashlib.sha256(
        json.dumps(values, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def validate_spine_dynamic_result(
    run: Mapping[str, object],
    result: Mapping[str, object],
    *,
    expected_profile_id: str,
    expected_core_mhz: float,
) -> list[str]:
    update_cycles = int(result.get("update_cycles", -1))
    maintenance_cycles = int(result.get("maintenance_cycles", -1))
    cold_cycles = int(result.get("cold_cycles", -1))
    total_cycles = int(result.get("cycles", -1))
    backend_requests = int(result.get("backend_requests", -1))
    cold_backend_requests = int(result.get("cold_backend_requests", -1))
    update_backend_requests = int(result.get("update_backend_requests", -1))
    checks = {
        "success": result.get("success") is True,
        "status": result.get("status") == "PASS",
        "mode": result.get("mode") == "spine_sssp",
        "profile": result.get("architecture_profile_id") == expected_profile_id,
        "clock": abs(float(result.get("core_mhz", -1.0)) - expected_core_mhz)
        < 1.0e-9,
        "dynamic": result.get("dynamic_update") is True,
        "path": result.get("dynamic_update_path")
        == expected_spine_update_path(str(run["scenario"])),
        "vertices": result.get("vertices")
        == run["graph"]["vertices"],  # type: ignore[index]
        "initial_edges": result.get("input_edges")
        == run["graph"]["records"],  # type: ignore[index]
        "update_records": result.get("update_edges") == run["physical_records"],
        "final_edges": result.get("materialized_snapshot_edges")
        == run["final_edges"],
        "architecture_correctness": result.get(
            "architecture_correctness_mismatches"
        )
        == 0,
        "mathematical_correctness": result.get(
            "mathematical_correctness_mismatches"
        )
        == 0,
        "combined_correctness": result.get("correctness_mismatches") == 0,
        "cold_correctness": result.get("cold_correctness_mismatches") == 0
        and result.get("cold_mathematical_correctness_mismatches") == 0,
        "full_recompute_correctness": result.get(
            "full_recompute_correctness_mismatches"
        )
        == 0,
        "frontier_correctness": result.get("frontier_mismatches") == 0
        and result.get("cold_frontier_mismatches") == 0,
        "converged": result.get("converged") is True,
        "cycle_window": update_cycles > 0
        and cold_cycles > 0
        and total_cycles == cold_cycles + update_cycles,
        "phase_order": maintenance_cycles > 0
        and maintenance_cycles <= update_cycles,
        "backend_window": update_backend_requests > 0
        and backend_requests == cold_backend_requests + update_backend_requests,
        "dram_closure": int(result.get("dram_reads", -1))
        + int(result.get("dram_writes", -1))
        == backend_requests,
        "memory_locality": result.get("memory_locality_ledger_match") is True
        and _memory_metrics_valid(result, system="spine"),
        "distance_count": isinstance(result.get("final_values"), list)
        and len(result["final_values"]) == run["graph"]["vertices"],  # type: ignore[index]
    }
    return [name for name, passed in checks.items() if not passed]


def validate_grasu_hls_result(
    run: Mapping[str, object],
    child: Mapping[str, object],
    *,
    expected_profile_sha256: str,
    expected_core_mhz: float,
) -> list[str]:
    result = child.get("result", {})
    dram = child.get("dram", {})
    if not isinstance(result, Mapping) or not isinstance(dram, Mapping):
        return ["child_shape"]
    cycles = int(result.get("cycles", -1))
    update_cycles = int(result.get("update_cycles", -1))
    compute_cycles = int(result.get("compute_cycles", -1))
    backend_requests = int(result.get("backend_requests", -1))
    update_backend_requests = int(result.get("update_backend_requests", -1))
    compute_backend_requests = int(result.get("compute_backend_requests", -1))
    checks = {
        "child_status": child.get("status") == "PASS",
        "success": result.get("success") is True,
        "mode": result.get("mode") == "grasu_regraph_hls_weighted_sssp",
        "profile": child.get("profile_sha256") == expected_profile_sha256,
        "clock": abs(float(result.get("core_mhz", -1.0)) - expected_core_mhz)
        < 1.0e-9,
        "vertices": result.get("vertices")
        == run["graph"]["vertices"],  # type: ignore[index]
        "initial_edges": result.get("initial_edges")
        == run["graph"]["records"],  # type: ignore[index]
        "logical_records": result.get("logical_updates")
        == run["physical_records"],
        "physical_records": result.get("physical_updates")
        == run["physical_records"],
        "architecture_correctness": result.get(
            "architecture_correctness_mismatches"
        )
        == 0,
        "mathematical_correctness": result.get(
            "mathematical_correctness_mismatches"
        )
        == 0,
        "combined_correctness": result.get("correctness_mismatches") == 0,
        "fixed_rounds": result.get("fixed_host_supersteps") is True
        and result.get("supersteps") == run["hls_host_supersteps"],
        "cycle_window": cycles > 0
        and update_cycles > 0
        and compute_cycles > 0
        and cycles == update_cycles + compute_cycles,
        "pma_ledger": result.get("update_pma_reads")
        == run["physical_records"]
        and result.get("update_pma_writes") == run["physical_records"],
        "backend_window": update_backend_requests > 0
        and compute_backend_requests > 0
        and update_backend_requests + compute_backend_requests
        == backend_requests,
        "dram_closure": int(dram.get("reads", -1))
        + int(dram.get("writes", -1))
        == backend_requests,
        "memory_locality": result.get("memory_locality_ledger_match") is True
        and _memory_metrics_valid(result, system="grasu_regraph"),
        "distance_count": isinstance(result.get("distances_external"), list)
        and len(result["distances_external"]) == run["graph"]["vertices"],  # type: ignore[index]
    }
    return [name for name, passed in checks.items() if not passed]


def system_row(
    run: Mapping[str, object],
    *,
    system: str,
    result: Mapping[str, object],
    dram: Mapping[str, object],
    wall_seconds: float,
    profile_id: str | None = None,
) -> dict[str, object]:
    if system == "spine":
        aligned_cycles = int(result["update_cycles"])
        structure_cycles = int(result["maintenance_cycles"])
        aligned_backend_requests = int(result["update_backend_requests"])
        total_backend_requests = int(result["backend_requests"])
        cold_cycles = int(result["cold_cycles"])
        cold_backend_requests = int(result["cold_backend_requests"])
        final_values = result["final_values"]
        axis_push_stalls = sum(
            int(value) for value in result.get("edge_axis_push_stalls_per_round", [])
        )
        dram_scope = "cold_plus_update_not_aligned"
        claim_class = "routed_reference_profile_execution_driven_simulation"
        resolved_profile_id = str(result["architecture_profile_id"])
        memory_metrics = spine_memory_metrics(result)
    elif system == "grasu_regraph":
        aligned_cycles = int(result["cycles"])
        structure_cycles = int(result["update_cycles"])
        aligned_backend_requests = int(result["backend_requests"])
        total_backend_requests = aligned_backend_requests
        cold_cycles = 0
        cold_backend_requests = 0
        final_values = result["distances_external"]
        axis_push_stalls = int(result["axis_push_stalls"])
        dram_scope = "aligned_update_plus_compute_active_channels"
        claim_class = result["claim_class"]
        if profile_id is None:
            raise ValueError("GraSU row requires a validated profile ID")
        resolved_profile_id = profile_id
        memory_metrics = grasu_memory_metrics(result)
    else:
        raise ValueError(f"unsupported system: {system}")

    core_mhz = float(result["core_mhz"])
    aligned_seconds = aligned_cycles / (core_mhz * 1_000_000.0)
    structure_seconds = structure_cycles / (core_mhz * 1_000_000.0)
    user_mutations = int(run["user_mutations"])
    physical_records = int(run["physical_records"])
    normalized = normalized_distances(final_values)
    return {
        "run_id": run["run_id"],
        "dataset_id": run["dataset_id"],
        "dataset_kind": run["dataset_kind"],
        "scenario": run["scenario"],
        "system": system,
        "claim_class": claim_class,
        "profile_id": resolved_profile_id,
        "core_mhz": core_mhz,
        "vertices": run["graph"]["vertices"],  # type: ignore[index]
        "initial_edges": run["graph"]["records"],  # type: ignore[index]
        "user_mutations": user_mutations,
        "physical_records": physical_records,
        "cold_cycles": cold_cycles,
        "aligned_e2e_cycles": aligned_cycles,
        "aligned_e2e_ms": aligned_seconds * 1_000.0,
        "structure_update_cycles": structure_cycles,
        "post_structure_cycles": aligned_cycles - structure_cycles,
        "user_mutations_per_second_e2e": user_mutations / aligned_seconds,
        "physical_records_per_second_e2e": physical_records / aligned_seconds,
        "user_mutations_per_second_structure": user_mutations / structure_seconds,
        "physical_records_per_second_structure": physical_records
        / structure_seconds,
        "cold_backend_requests": cold_backend_requests,
        "aligned_backend_requests": aligned_backend_requests,
        "total_backend_requests": total_backend_requests,
        **memory_metrics,
        "axis_push_stalls": axis_push_stalls,
        "dram_reads": int(dram["reads"]),
        "dram_writes": int(dram["writes"]),
        "dram_activates": int(dram["activates"]),
        "dram_precharges": int(dram["precharges"]),
        "dram_energy_pj": float(dram["total_energy_pj"]),
        "dram_window_scope": dram_scope,
        "host_wall_seconds": wall_seconds,
        "correctness_mismatches": int(result["correctness_mismatches"]),
        "distance_vector_sha256": distance_vector_sha256(normalized),
        "normalized_distances": normalized,
    }


def pair_row(
    spine: Mapping[str, object], grasu: Mapping[str, object]
) -> dict[str, object]:
    if spine["run_id"] != grasu["run_id"]:
        raise ValueError("cannot pair different run IDs")
    distances_match = spine["normalized_distances"] == grasu["normalized_distances"]
    if not distances_match:
        raise ValueError(f"cross-system distance mismatch for {spine['run_id']}")
    return {
        "run_id": spine["run_id"],
        "dataset_id": spine["dataset_id"],
        "scenario": spine["scenario"],
        "user_mutations": spine["user_mutations"],
        "physical_records": spine["physical_records"],
        "spine_aligned_e2e_ms": spine["aligned_e2e_ms"],
        "grasu_aligned_e2e_ms": grasu["aligned_e2e_ms"],
        "spine_speedup_over_grasu_e2e": float(grasu["aligned_e2e_ms"])
        / float(spine["aligned_e2e_ms"]),
        "spine_structure_update_ms": float(spine["structure_update_cycles"])
        / (float(spine["core_mhz"]) * 1_000.0),
        "grasu_structure_update_ms": float(grasu["structure_update_cycles"])
        / (float(grasu["core_mhz"]) * 1_000.0),
        "grasu_to_spine_aligned_backend_request_ratio": float(
            grasu["aligned_backend_requests"]
        )
        / float(spine["aligned_backend_requests"]),
        "grasu_to_spine_aligned_backend_byte_ratio": float(
            grasu["backend_bytes"]
        )
        / float(spine["aligned_backend_bytes"]),
        "cross_system_distances_match": distances_match,
        "dram_energy_ratio_valid": False,
        "dram_energy_ratio_reason": "Spine DRAM counters include cold plus update",
        "claim_label": "profile_clock_adjusted_real_compact_execution_driven",
    }
