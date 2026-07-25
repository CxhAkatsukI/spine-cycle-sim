"""Contracts for profile-clock-adjusted real compact Full PageRank runs."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Mapping


RANK_TOLERANCE = 1.0e-5
BACKEND_LINE_BYTES = 64


def rank_vector(values: object) -> tuple[float, ...]:
    if not isinstance(values, list) or not values:
        raise ValueError("PageRank vector is missing")
    ranks = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in ranks):
        raise ValueError("PageRank vector contains a non-finite value")
    return ranks


def rank_vector_sha256(values: tuple[float, ...]) -> str:
    return hashlib.sha256(
        json.dumps(values, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def validate_spine_pagerank_result(
    run: Mapping[str, object],
    result: Mapping[str, object],
    *,
    expected_profile_id: str,
    expected_core_mhz: float,
    iterations: int,
    damping: float,
) -> list[str]:
    cycles = int(result.get("cycles", -1))
    update_cycles = int(result.get("maintenance_cycles", -1))
    update_requests = int(result.get("maintenance_backend_requests", -1))
    compute_requests = int(result.get("compute_backend_requests", -1))
    backend_requests = int(result.get("backend_requests", -1))
    checks = {
        "success": result.get("success") is True,
        "status": result.get("status") == "PASS",
        "mode": result.get("mode") == "spine_pagerank",
        "profile": result.get("architecture_profile_id") == expected_profile_id,
        "clock": abs(float(result.get("core_mhz", -1.0)) - expected_core_mhz)
        < 1.0e-9,
        "dynamic": result.get("dynamic_update") is True,
        "pipeline": result.get("pipeline_order")
        == "zero_time_l0_preload_then_update_maintenance_then_compute",
        "vertices": result.get("vertices")
        == run["graph"]["vertices"],  # type: ignore[index]
        "initial_edges": result.get("initial_edges")
        == run["graph"]["records"],  # type: ignore[index]
        "update_records": result.get("update_edges") == run["physical_records"],
        "final_edges": result.get("materialized_snapshot_edges")
        == run["final_edges"]
        and result.get("maintenance_persisted_edges") == run["final_edges"],
        "iterations": result.get("pagerank_iterations") == iterations
        and result.get("pagerank_completed_iterations") == iterations
        and len(result.get("iteration_cycles", [])) == iterations,
        "damping": abs(float(result.get("pagerank_damping", -1.0)) - damping)
        < 1.0e-7,
        "architecture_correctness": result.get(
            "architecture_correctness_mismatches"
        )
        == 0,
        "mathematical_correctness": result.get(
            "mathematical_correctness_mismatches"
        )
        == 0,
        "combined_correctness": result.get("correctness_mismatches") == 0,
        "rank_error": float(result.get("max_abs_error", math.inf))
        <= RANK_TOLERANCE
        and float(result.get("mathematical_max_abs_error", math.inf))
        <= RANK_TOLERANCE,
        "rank_count": isinstance(result.get("ranks"), list)
        and len(result["ranks"]) == run["graph"]["vertices"],  # type: ignore[index]
        "cycle_window": cycles > update_cycles > 0,
        "backend_window": update_requests > 0
        and compute_requests > 0
        and update_requests + compute_requests == backend_requests,
        "dram_closure": int(result.get("dram_reads", -1))
        + int(result.get("dram_writes", -1))
        == backend_requests,
    }
    return [name for name, passed in checks.items() if not passed]


def validate_grasu_pagerank_result(
    run: Mapping[str, object],
    child: Mapping[str, object],
    *,
    expected_profile_sha256: str,
    expected_core_mhz: float,
    iterations: int,
    damping: float,
) -> list[str]:
    result = child.get("result", {})
    dram = child.get("dram", {})
    if not isinstance(result, Mapping) or not isinstance(dram, Mapping):
        return ["child_shape"]
    cycles = int(result.get("cycles", -1))
    update_cycles = int(result.get("update_cycles", -1))
    compute_cycles = int(result.get("compute_cycles", -1))
    update_requests = int(result.get("update_backend_requests", -1))
    compute_requests = int(result.get("compute_backend_requests", -1))
    backend_requests = int(result.get("backend_requests", -1))
    checks = {
        "child_status": child.get("status") == "PASS",
        "success": result.get("success") is True,
        "mode": result.get("mode") == "grasu_regraph_hls_weighted_pagerank",
        "claim": result.get("claim_class")
        == "hls_equivalent_proposed_execution_driven_simulation",
        "profile": child.get("profile_sha256") == expected_profile_sha256,
        "clock": abs(float(result.get("core_mhz", -1.0)) - expected_core_mhz)
        < 1.0e-9,
        "pipeline": result.get("pipeline_order")
        == "update_then_degree_barrier_then_pma_native_compute",
        "vertices": result.get("vertices")
        == run["graph"]["vertices"],  # type: ignore[index]
        "initial_edges": result.get("initial_edges")
        == run["graph"]["records"],  # type: ignore[index]
        "logical_records": result.get("logical_updates")
        == run["physical_records"],
        "physical_records": result.get("physical_updates")
        == run["physical_records"],
        "iterations": result.get("iterations") == iterations,
        "damping": abs(float(result.get("pagerank_damping", -1.0)) - damping)
        < 1.0e-7,
        "final_edges": result.get("compute_live_edges")
        == int(run["final_edges"]) * iterations,
        "architecture_correctness": result.get(
            "architecture_correctness_mismatches"
        )
        == 0,
        "mathematical_correctness": result.get(
            "mathematical_correctness_mismatches"
        )
        == 0,
        "combined_correctness": result.get("correctness_mismatches") == 0,
        "rank_error": float(result.get("max_abs_error", math.inf))
        <= RANK_TOLERANCE
        and float(result.get("mathematical_max_abs_error", math.inf))
        <= RANK_TOLERANCE,
        "rank_count": isinstance(result.get("ranks_external"), list)
        and len(result["ranks_external"])
        == run["graph"]["vertices"],  # type: ignore[index]
        "cycle_window": cycles > 0
        and update_cycles > 0
        and compute_cycles > 0
        and cycles == update_cycles + compute_cycles,
        "update_ledger": result.get("update_pma_reads")
        == run["physical_records"]
        and result.get("update_pma_writes") == run["physical_records"]
        and result.get("degree_update_reads") == run["physical_records"]
        and result.get("degree_update_writes") == run["physical_records"],
        "backend_window": update_requests > 0
        and compute_requests > 0
        and update_requests + compute_requests == backend_requests
        and result.get("expected_backend_requests") == backend_requests,
        "dram_closure": int(dram.get("reads", -1))
        + int(dram.get("writes", -1))
        == backend_requests,
    }
    return [name for name, passed in checks.items() if not passed]


def system_row(
    run: Mapping[str, object],
    *,
    system: str,
    result: Mapping[str, object],
    dram: Mapping[str, object],
    wall_seconds: float,
    profile_id: str,
) -> dict[str, object]:
    if system == "spine":
        cycles = int(result["cycles"])
        update_cycles = int(result["maintenance_cycles"])
        compute_cycles = cycles - update_cycles
        update_requests = int(result["maintenance_backend_requests"])
        compute_requests = int(result["compute_backend_requests"])
        ranks = rank_vector(result["ranks"])
        axis_push_stalls = int(result.get("edge_axis_push_stalls", 0))
        claim_class = "routed_reference_profile_execution_driven_simulation"
    elif system == "grasu_regraph":
        cycles = int(result["cycles"])
        update_cycles = int(result["update_cycles"])
        compute_cycles = int(result["compute_cycles"])
        update_requests = int(result["update_backend_requests"])
        compute_requests = int(result["compute_backend_requests"])
        ranks = rank_vector(result["ranks_external"])
        axis_push_stalls = int(result.get("axis_push_stalls", 0))
        claim_class = str(result["claim_class"])
    else:
        raise ValueError(f"unsupported system: {system}")

    core_mhz = float(result["core_mhz"])
    e2e_seconds = cycles / (core_mhz * 1_000_000.0)
    update_seconds = update_cycles / (core_mhz * 1_000_000.0)
    compute_seconds = compute_cycles / (core_mhz * 1_000_000.0)
    user_mutations = int(run["user_mutations"])
    physical_records = int(run["physical_records"])
    backend_requests = int(result["backend_requests"])
    return {
        "run_id": run["run_id"],
        "dataset_id": run["dataset_id"],
        "dataset_kind": run["dataset_kind"],
        "scenario": run["scenario"],
        "algorithm": "full_pagerank",
        "system": system,
        "claim_class": claim_class,
        "profile_id": profile_id,
        "core_mhz": core_mhz,
        "vertices": run["graph"]["vertices"],  # type: ignore[index]
        "initial_edges": run["graph"]["records"],  # type: ignore[index]
        "final_edges": run["final_edges"],
        "user_mutations": user_mutations,
        "physical_records": physical_records,
        "e2e_cycles": cycles,
        "e2e_ms": e2e_seconds * 1_000.0,
        "update_cycles": update_cycles,
        "update_ms": update_seconds * 1_000.0,
        "compute_cycles": compute_cycles,
        "compute_ms": compute_seconds * 1_000.0,
        "user_mutations_per_second_update": user_mutations / update_seconds,
        "physical_records_per_second_update": physical_records / update_seconds,
        "backend_requests": backend_requests,
        "backend_bytes": backend_requests * BACKEND_LINE_BYTES,
        "update_backend_requests": update_requests,
        "update_backend_bytes": update_requests * BACKEND_LINE_BYTES,
        "compute_backend_requests": compute_requests,
        "compute_backend_bytes": compute_requests * BACKEND_LINE_BYTES,
        "axis_push_stalls": axis_push_stalls,
        "dram_reads": int(dram["reads"]),
        "dram_writes": int(dram["writes"]),
        "dram_activates": int(dram["activates"]),
        "dram_precharges": int(dram["precharges"]),
        "dram_energy_pj": float(dram["total_energy_pj"]),
        "dram_window_scope": "update_plus_compute_active_channels",
        "host_wall_seconds": wall_seconds,
        "correctness_mismatches": int(result["correctness_mismatches"]),
        "rank_vector_sha256": rank_vector_sha256(ranks),
        "ranks": ranks,
    }


def pair_row(
    spine: Mapping[str, object], grasu: Mapping[str, object]
) -> dict[str, object]:
    if spine["run_id"] != grasu["run_id"]:
        raise ValueError("cannot pair different run IDs")
    spine_ranks = tuple(float(value) for value in spine["ranks"])
    grasu_ranks = tuple(float(value) for value in grasu["ranks"])
    if len(spine_ranks) != len(grasu_ranks):
        raise ValueError(f"rank count mismatch for {spine['run_id']}")
    max_abs_difference = max(
        abs(left - right) for left, right in zip(spine_ranks, grasu_ranks, strict=True)
    )
    if max_abs_difference > RANK_TOLERANCE:
        raise ValueError(f"cross-system rank mismatch for {spine['run_id']}")
    return {
        "run_id": spine["run_id"],
        "dataset_id": spine["dataset_id"],
        "scenario": spine["scenario"],
        "user_mutations": spine["user_mutations"],
        "physical_records": spine["physical_records"],
        "spine_e2e_ms": spine["e2e_ms"],
        "grasu_e2e_ms": grasu["e2e_ms"],
        "spine_speedup_over_grasu_e2e": float(grasu["e2e_ms"])
        / float(spine["e2e_ms"]),
        "spine_update_ms": spine["update_ms"],
        "grasu_update_ms": grasu["update_ms"],
        "spine_speedup_over_grasu_update": float(grasu["update_ms"])
        / float(spine["update_ms"]),
        "spine_compute_ms": spine["compute_ms"],
        "grasu_compute_ms": grasu["compute_ms"],
        "spine_speedup_over_grasu_compute": float(grasu["compute_ms"])
        / float(spine["compute_ms"]),
        "grasu_to_spine_backend_request_ratio": float(grasu["backend_requests"])
        / float(spine["backend_requests"]),
        "grasu_to_spine_update_request_ratio": float(
            grasu["update_backend_requests"]
        )
        / float(spine["update_backend_requests"]),
        "grasu_to_spine_compute_request_ratio": float(
            grasu["compute_backend_requests"]
        )
        / float(spine["compute_backend_requests"]),
        "cross_system_max_abs_rank_difference": max_abs_difference,
        "cross_system_ranks_match": True,
        "dram_energy_ratio_valid": False,
        "dram_energy_ratio_reason": (
            "active-channel DRAM only; on-chip and idle-channel energy excluded"
        ),
        "claim_label": "profile_clock_adjusted_real_compact_execution_driven",
    }
