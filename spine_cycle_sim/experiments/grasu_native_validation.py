"""Native GraSU/ReGraph capability, topology, and result gates.

The native CLI re-exports these names for existing callers.
"""

from __future__ import annotations

import json
from pathlib import Path

from .profile_capabilities import (
    AlgorithmCapability,
    CapabilityCatalog,
    load_capability_catalog,
)


def native_active_hbm_channels(profile: dict[str, object]) -> tuple[int, ...]:
    """Derive the HBM channels reachable by the pinned native HLS topology."""

    memory = profile.get("memory")
    params = profile.get("parameters")
    if not isinstance(memory, dict) or not isinstance(params, dict):
        raise ValueError("native profile requires memory and parameters objects")
    physical_channels = int(memory["channels"])
    first_pma = int(params["grasu_pma_hbm_first_channel"])
    pma_channels = int(params["grasu_pma_hbm_channels"])
    active = set(range(first_pma, first_pma + pma_channels))
    for field in (
        "pma_compactor_row_channel",
        "regraph_edge_array_channel",
        "regraph_source_state_channel",
        "regraph_source_state_mirror_channel",
        "regraph_vertex_prop_hbm_channel",
    ):
        active.add(int(params[field]))
    ordered = tuple(sorted(active))
    if not ordered or ordered[0] < 0 or ordered[-1] >= physical_channels:
        raise ValueError(
            "native HLS topology references an out-of-range HBM channel"
        )
    return ordered


def require_native_algorithm_capability(
    profile_path: Path, capability_catalog_path: Path
) -> tuple[CapabilityCatalog, AlgorithmCapability]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile_id = str(profile.get("profile_id", ""))
    catalog = load_capability_catalog(capability_catalog_path)
    profile_capability = catalog.profile(profile_id)
    if profile_capability.profile_path != profile_path.resolve():
        raise ValueError(
            "native capability profile path does not match the selected profile"
        )
    capability = profile_capability.require("unit_weight_sssp")
    if (
        profile_capability.comparison_role != "native"
        or profile_capability.handoff != "pma_to_compact_edge_array"
        or profile_capability.conversion_cost != "included"
    ):
        raise ValueError("native capability does not describe the existing HLS path")
    return catalog, capability


def validate_result(
    result: dict[str, object],
    profile: dict[str, object],
    expected_source_external: int | None = None,
) -> None:
    params = profile["parameters"]
    assert isinstance(params, dict)
    supersteps = int(result.get("supersteps", -1))
    compact_slots = int(result.get("compact_edge_slots", -1))
    final_edges = int(result.get("final_edges", -1))
    vertices = int(result.get("vertices", -1))
    apply_bursts = params["regraph_partition_vertices"] // 16 * supersteps
    expected_edge_bursts = compact_slots // 8 * supersteps
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "grasu_regraph_native_sssp",
        "claim": result.get("claim_class") == "native_structural_simulation",
        "backend": result.get("backend") == "sst_memHierarchy_dramsim3",
        "conversion": result.get("conversion_cost_included") is True,
        "host_reorder": result.get("native_host_vertex_reorder") is True,
        "source_alias": result.get("source") == result.get("source_internal"),
        "source_external": expected_source_external is None
        or result.get("source_external") == expected_source_external,
        "serial_order": result.get("pipeline_order")
        == "update_then_barrier_compactor_then_compute",
        "ledger": result.get("cycles")
        == result.get("component_cycles", -1) + result.get("controller_gap_cycles", -2),
        "correctness": result.get("correctness_mismatches") == 0,
        "hls_contract": result.get("native_hls_contract_safe") is True,
        "cross_window": result.get("cross_source_round_bursts") == 0,
        "abi": result.get("pma_edge_abi") == "native_raw_destination32",
        "supersteps": supersteps == params["native_validation_supersteps"],
        "barrier_tokens": result.get("completion_token_reads")
        == params["pma_compactor_completion_tokens"],
        "barrier_cycles": result.get("barrier_cycles")
        == params["pma_compactor_completion_tokens"],
        "row_scan": result.get("compactor_row_reads") == vertices + 1,
        "pma_scan": result.get("compactor_pma_slots_scanned")
        == result.get("pma_slots"),
        "valid_edges": result.get("compactor_valid_edges") == final_edges,
        "dummy_edges": result.get("compactor_dummy_edge_slots")
        == compact_slots - final_edges,
        "edge_writes": result.get("compactor_edge_array_writes")
        == compact_slots // 8,
        "edge_requests": result.get("edge_array_requests") == supersteps,
        "edge_bursts": result.get("edge_array_bursts") == expected_edge_bursts,
        "edge_slots": result.get("edge_array_slots_scanned")
        == compact_slots * supersteps,
        "edge_bytes": result.get("edge_array_read_bytes")
        == compact_slots * 8 * supersteps,
        "apply_reads": result.get("apply_state_reads") == apply_bursts,
        "apply_writes": result.get("apply_state_writes") == apply_bursts,
        "source_mirrors": result.get("compute_source_state_writes")
        == params["regraph_source_state_copies"] * apply_bursts,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"native SST validation failed ({failed}): {result}")
