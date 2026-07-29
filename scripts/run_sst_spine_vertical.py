#!/usr/bin/env python3
"""Run and validate the real Spine vertical slice on SST-HBM."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.sst_binding import spine_memory_binding  # noqa: E402
from spine_cycle_sim.sst_library import forced_sst_library_binding  # noqa: E402


DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_WORKLOAD = ROOT / "tests" / "data" / "amazon_top1_exact.slice"
DEFAULT_CARRY_WORKLOAD = ROOT / "tests" / "data" / "carry_hot_batch.slice"
DEFAULT_CARRY_PRELOAD = ROOT / "tests" / "data" / "carry_hot_preload.slice"
DEFAULT_FULL_WORKLOAD = (
    ROOT / "tests" / "data" / "amazon_densewin8192_active7893_exact.slice"
)
DEFAULT_SSSP_WORKLOAD = ROOT / "tests" / "data" / "weighted_chain_shortcut.slice"
DEFAULT_DYNAMIC_SSSP_WORKLOAD = (
    ROOT / "tests" / "data" / "dynamic_shortcut_initial.slice"
)
DEFAULT_DYNAMIC_SSSP_UPDATE = (
    ROOT / "tests" / "data" / "dynamic_shortcut_update.slice"
)
DEFAULT_NONMONOTONIC_SSSP_WORKLOAD = (
    ROOT / "tests" / "data" / "dynamic_nonmonotonic_initial.slice"
)
DEFAULT_DELETE_SSSP_UPDATE = (
    ROOT / "tests" / "data" / "dynamic_delete_update.slice"
)
DEFAULT_INCREASE_SSSP_UPDATE = (
    ROOT / "tests" / "data" / "dynamic_weight_increase_update.slice"
)
DEFAULT_PAGERANK_WORKLOAD = (
    ROOT / "tests" / "data" / "pagerank_four_vertex.slice"
)
DEFAULT_PROTOCOL_WORKLOAD = (
    ROOT / "tests" / "data" / "source_protocol_window_17.slice"
)
DEFAULT_FALLBACK_WORKLOAD = (
    ROOT / "tests" / "data" / "fallback_three_tiles.slice"
)
PROFILE_PATH = ROOT / "configs" / "architectures" / "spine_shared_engine_9c08763.json"


def load_slice_shape(path: Path) -> tuple[int, int]:
    vertices: int | None = None
    records = 0
    with path.open("r", encoding="ascii") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                metadata = line[1:].strip()
                if metadata.startswith("vertices="):
                    vertices = int(metadata.split("=", 1)[1])
                continue
            if len(line.split()) != 4:
                raise ValueError(f"{path}:{line_number}: expected four edge fields")
            records += 1
    if vertices is None or vertices <= 0:
        raise ValueError(f"{path}: missing positive vertices metadata")
    return vertices, records


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_generic_result(
    result: dict[str, Any],
    dram: dict[str, int | float],
    *,
    channels: int,
    scenario: str,
    vertices: int,
    input_edges: int,
    update_edges: int,
    source: int,
    core_mhz: float,
    max_rounds: int,
    pagerank_iterations: int,
    pagerank_damping: float,
    pagerank_epsilon: float,
    residual_max_iterations: int,
    residual_contract: str = "generic_dangling_l1_cold",
) -> list[str]:
    expected_mode = {
        "weighted_sssp": "spine_sssp",
        "dynamic_sssp": "spine_sssp",
        "dynamic_sssp_delete": "spine_sssp",
        "dynamic_sssp_increase": "spine_sssp",
        "full_pagerank": "spine_pagerank",
        "residual_pagerank": "spine_residual_pagerank",
    }[scenario]
    checks: dict[str, bool] = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == expected_mode,
        "core_mhz": abs(float(result.get("core_mhz", -1.0)) - core_mhz) < 1.0e-9,
        "input_edges": result.get("input_edges") == input_edges,
        "architecture_oracle": bool(result.get("architecture_oracle")),
        "mathematical_oracle": bool(result.get("mathematical_oracle")),
        "architecture_correctness": (
            result.get("architecture_correctness_mismatches") == 0
        ),
        "mathematical_correctness": (
            result.get("mathematical_correctness_mismatches") == 0
        ),
        "combined_correctness": result.get("correctness_mismatches") == 0,
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    if expected_mode in {"spine_pagerank", "spine_residual_pagerank"}:
        dynamic = update_edges > 0
        checks.update(
            {
                "dynamic_flag": (not dynamic)
                or result.get("dynamic_update") is True,
                "initial_edges": (not dynamic)
                or result.get("initial_edges") == input_edges,
                "update_edges": (not dynamic)
                or result.get("update_edges") == update_edges,
                "materialized_snapshot": (not dynamic)
                or (
                    isinstance(result.get("materialized_snapshot_edges"), int)
                    and result["materialized_snapshot_edges"] > 0
                    and isinstance(result.get("maintenance_persisted_edges"), int)
                    and 0
                    <= result["maintenance_persisted_edges"]
                    <= result["materialized_snapshot_edges"]
                ),
                "materialized_reader": (not dynamic)
                or expected_mode != "spine_pagerank"
                or result.get("reader_edges")
                == result.get("materialized_snapshot_edges"),
                "dynamic_pipeline_order": (not dynamic)
                or result.get("pipeline_order")
                == "zero_time_resident_level_preload_then_update_maintenance_then_compute",
                "phase_backend_ledger": (not dynamic)
                or (
                    int(result.get("maintenance_backend_requests", -1)) > 0
                    and int(result.get("compute_backend_requests", -1)) > 0
                    and int(result["maintenance_backend_requests"])
                    + int(result["compute_backend_requests"])
                    == int(result.get("backend_requests", -1))
                ),
            }
        )
    if expected_mode == "spine_sssp":
        rounds = result.get("rounds", -1)
        dynamic = scenario != "weighted_sssp"
        expected_update_path = (
            "incremental_relax" if scenario == "dynamic_sssp" else "full_rebuild"
        )
        per_round_fields = (
            "frontier_in_sizes",
            "frontier_out_sizes",
            "reader_protocol_status_per_round",
            "compute_protocol_status_per_round",
            "reader_memory_requests_issued_per_round",
            "reader_memory_requests_completed_per_round",
            "compute_memory_requests_issued_per_round",
            "compute_memory_requests_completed_per_round",
        )
        checks.update(
            {
                "vertices": result.get("vertices") == vertices,
                "source": result.get("source") == source,
                "converged": result.get("converged") is True,
                "rounds": isinstance(rounds, int) and 0 < rounds <= max_rounds,
                "final_values": len(result.get("final_values", [])) == vertices,
                "frontier_correctness": result.get("frontier_mismatches") == 0,
                "round_ledgers": all(
                    len(result.get(field, [])) == rounds for field in per_round_fields
                ),
                "protocol_status": all(
                    value == 0
                    for field in (
                        "reader_protocol_status_per_round",
                        "compute_protocol_status_per_round",
                    )
                    for value in result.get(field, [-1])
                ),
                "reader_request_closure": result.get(
                    "reader_memory_requests_issued_per_round"
                )
                == result.get("reader_memory_requests_completed_per_round"),
                "compute_request_closure": result.get(
                    "compute_memory_requests_issued_per_round"
                )
                == result.get("compute_memory_requests_completed_per_round"),
                "dynamic_flag": result.get("dynamic_update") is dynamic,
                "update_edges": (not dynamic)
                or result.get("update_edges") == update_edges,
                "update_path": (not dynamic)
                or result.get("dynamic_update_path") == expected_update_path,
                "cold_correctness": (not dynamic)
                or (
                    result.get("cold_correctness_mismatches") == 0
                    and result.get("cold_mathematical_correctness_mismatches") == 0
                    and result.get("cold_frontier_mismatches") == 0
                    and result.get("full_recompute_correctness_mismatches") == 0
                ),
            }
        )
    elif expected_mode == "spine_pagerank":
        checks.update(
            {
                "vertices": result.get("vertices") == vertices,
                "iterations": result.get("pagerank_iterations")
                == pagerank_iterations
                and result.get("pagerank_completed_iterations")
                == pagerank_iterations
                and len(result.get("iteration_cycles", []))
                == pagerank_iterations,
                "damping": abs(
                    float(result.get("pagerank_damping", -1.0))
                    - pagerank_damping
                )
                < 1.0e-7,
                "rank_vector": len(result.get("ranks", [])) == vertices,
                "architecture_error": result.get("max_abs_error", 1.0)
                <= 1.0e-5,
                "mathematical_error": result.get(
                    "mathematical_max_abs_error", 1.0
                )
                <= 1.0e-5,
                "reader_protocol": result.get("reader_protocol_status") == 0,
            }
        )
    else:
        rounds = result.get("iterations", -1)
        delta_hls = residual_contract == "deltahls_sink_free_linf_warm"
        residual_measure = (
            result.get("residual_linf", float("inf"))
            if delta_hls
            else result.get("residual_l1", float("inf"))
        )
        checks.update(
            {
                "vertices": result.get("vertices") == vertices,
                "converged": result.get("converged") is True
                and result.get("final_active") == 0,
                "iterations": isinstance(rounds, int)
                and 0 < rounds <= residual_max_iterations,
                "damping": abs(
                    float(result.get("pagerank_damping", -1.0))
                    - pagerank_damping
                )
                < 1.0e-7,
                "epsilon": abs(
                    float(result.get("pagerank_epsilon", -1.0))
                    - pagerank_epsilon
                )
                < 1.0e-12,
                "residual_contract": result.get("residual_contract")
                == residual_contract,
                "sink_free": (not delta_hls)
                or (
                    result.get("old_sink_vertices") == 0
                    and result.get("new_sink_vertices") == 0
                ),
                "state_vectors": len(result.get("ranks", [])) == vertices
                and len(result.get("residuals", [])) == vertices,
                "frontier_ledgers": len(result.get("frontier_in_sizes", []))
                == rounds
                and len(result.get("frontier_out_sizes", [])) == rounds,
                "frontier_match": result.get("frontier_match") is True,
                "memory_ledger": result.get("memory_ledger_match") is True,
                "residual_bound": result.get("residual_bound_passed") is True
                and float(residual_measure) <= pagerank_epsilon * 1.01,
                "architecture_error": result.get("max_abs_error", 1.0)
                <= 1.0e-5,
                "mathematical_error": result.get(
                    "mathematical_max_abs_error", 1.0
                )
                <= result.get("mathematical_error_tolerance", -1.0),
                "reader_protocol": result.get("reader_protocol_status") == 0,
            }
        )
    return [name for name, passed in checks.items() if not passed]


def validate_candidate10_maintenance_result(
    result: dict[str, Any],
    dram: dict[str, int | float],
    *,
    channels: int,
    input_edges: int,
    core_mhz: float,
) -> list[str]:
    candidate_visits = int(
        result.get("maintenance_candidate_classify_edge_visits", -1)
    )
    dispatch_reads = int(result.get("maintenance_dispatch_input_reads", -1))
    dispatch_writes = int(result.get("maintenance_dispatch_bucket_writes", -1))
    target_level = int(result.get("maintenance_target_level", -1))
    expected_precount_visits = input_edges if target_level == 0 else 0
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_maintenance",
        "architecture": (
            result.get("spine_maintenance_architecture")
            == "candidate10_one_pass"
        ),
        "core_mhz": abs(float(result.get("core_mhz", -1.0)) - core_mhz)
        < 1.0e-9,
        "input_edges": result.get("input_edges") == input_edges,
        "maintenance_timed": int(result.get("maintenance_cycles", 0)) > 0,
        "classify_closure": candidate_visits == input_edges,
        "dispatch_read_closure": dispatch_reads == input_edges,
        "dispatch_write_closure": dispatch_writes == input_edges,
        "l0_precount_closure": (
            result.get("maintenance_candidate_l0_precount_edge_visits")
            == expected_precount_visits
        ),
        "dispatch_status": result.get("maintenance_dispatch_status") == 0,
        "dispatch_cursor_closure": (
            result.get("maintenance_dispatch_cursor_mismatches") == 0
        ),
        "publication_complete": (
            result.get("maintenance_publication_complete") is True
        ),
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def maintenance_timing_profile_matches(
    result: dict[str, Any], expected: dict[str, int]
) -> bool:
    if result.get("mode") == "spine_compute":
        return True
    return all(result.get(field) == value for field, value in expected.items())


def maintenance_scan_ledger_matches(
    result: dict[str, Any],
    *,
    edges: int,
    unique_sources: int,
    family_precount_visits: int,
    l0_write_visits: int,
) -> bool:
    expected_visits = 3 * edges + family_precount_visits + l0_write_visits
    source_shaped = result.get("spine_axi_profile") == "hls_split_9c08763"
    response_capacity = result.get("maintenance_scan_response_capacity", 32)
    return (
        result.get("maintenance_dirty_validate_visits") == edges
        and result.get("maintenance_dirty_mark_visits") == edges
        and result.get("maintenance_dirty_unique_sources") == unique_sources
        and result.get("maintenance_dirty_bitmap_reads") == unique_sources
        and result.get("maintenance_dirty_bitmap_writes") == unique_sources
        and result.get("maintenance_dirty_list_reads") == unique_sources
        and result.get("maintenance_dirty_list_appends") == unique_sources
        and result.get("maintenance_dirty_duplicates_suppressed")
        == edges - unique_sources
        and result.get("maintenance_dirty_generation_advances") == 1
        and result.get("maintenance_dirty_count") == unique_sources
        and result.get("maintenance_dirty_generation") == 1
        and result.get("maintenance_hot_cold_count_visits") == edges
        and result.get("maintenance_family_precount_visits")
        == family_precount_visits
        and result.get("maintenance_l0_write_visits") == l0_write_visits
        and result.get("maintenance_edge_visits") == expected_visits
        and (
            (
                result.get("maintenance_sorted_read_beats") == expected_visits
                and result.get("maintenance_sorted_axi_read_beats_streamed")
                == expected_visits
                and 0
                < result.get("maintenance_max_scan_buffered_edges", 0)
                <= response_capacity
            )
            if source_shaped
            else result.get("maintenance_sorted_read_beats") == 0
        )
    )


def diagnostic_transcript_matches(result: dict[str, Any]) -> bool:
    field_pairs = (
        ("reader_range_path", "compute_range_path"),
        ("reader_range_fallback_reason", "compute_range_fallback_reason"),
        ("reader_range_error", "compute_range_error"),
        ("reader_range_tasks", "compute_range_tasks"),
        ("reader_range_row_lookups", "compute_range_row_lookups"),
        (
            "reader_range_construction_payloads",
            "compute_range_construction_payloads",
        ),
        ("reader_range_replay_payloads", "compute_range_replay_payloads"),
        ("reader_range_active_records", "compute_range_active_records"),
        ("reader_range_family_probes", "compute_range_family_probes"),
        ("reader_range_family_skips", "compute_range_family_skips"),
    )
    return (
        result.get("reader_diagnostic_words") == 10
        and result.get("reader_done_words") == 1
        and result.get("reader_done_overflow") == 0
        and result.get("compute_diagnostic_words") == 10
        and result.get("compute_done_words") == 1
        and result.get("compute_done_overflow") == 0
        and result.get("reader_metadata_write_bytes") == 16
        and result.get("reader_result_write_bytes") == 64
        and result.get("compute_dirty_count") == result.get("reader_source_requests")
        and result.get("compute_dirty_generation") == 1
        and all(result.get(reader) == result.get(compute) for reader, compute in field_pairs)
    )


def multiround_diagnostic_transcript_matches(result: dict[str, Any]) -> bool:
    rounds = result.get("rounds")
    if not isinstance(rounds, int):
        return False
    field_pairs = (
        ("reader_range_paths_per_round", "compute_range_paths_per_round"),
        (
            "reader_range_fallback_reasons_per_round",
            "compute_range_fallback_reasons_per_round",
        ),
        ("reader_range_errors_per_round", "compute_range_errors_per_round"),
        ("reader_range_tasks_per_round", "compute_range_tasks_per_round"),
        (
            "reader_range_row_lookups_per_round",
            "compute_range_row_lookups_per_round",
        ),
        (
            "reader_range_construction_payloads_per_round",
            "compute_range_construction_payloads_per_round",
        ),
        (
            "reader_range_replay_payloads_per_round",
            "compute_range_replay_payloads_per_round",
        ),
        (
            "reader_range_active_records_per_round",
            "compute_range_active_records_per_round",
        ),
        (
            "reader_range_family_probes_per_round",
            "compute_range_family_probes_per_round",
        ),
        (
            "reader_range_family_skips_per_round",
            "compute_range_family_skips_per_round",
        ),
    )
    return (
        result.get("reader_diagnostic_words_per_round") == [10] * rounds
        and result.get("reader_done_words_per_round") == [1] * rounds
        and result.get("reader_done_overflow_per_round") == [0] * rounds
        and result.get("compute_diagnostic_words_per_round") == [10] * rounds
        and result.get("compute_done_words_per_round") == [1] * rounds
        and result.get("compute_done_overflow_per_round") == [0] * rounds
        and result.get("reader_metadata_write_bytes_per_round") == [16] * rounds
        and result.get("reader_result_write_bytes_per_round") == [64] * rounds
        and result.get("reader_dirty_counts_per_round")
        == result.get("compute_dirty_counts_per_round")
        and result.get("reader_dirty_generations_per_round")
        == result.get("compute_dirty_generations_per_round")
        and all(result.get(reader) == result.get(compute) for reader, compute in field_pairs)
    )


def collect_dram_stats(out_dir: Path) -> dict[str, int | float]:
    totals: dict[str, int | float] = {
        "dram_channels": 0,
        "dram_reads": 0,
        "dram_writes": 0,
        "dram_activates": 0,
        "dram_precharges": 0,
        "dram_read_row_hits": 0,
        "dram_write_row_hits": 0,
        "dram_total_energy_pj": 0.0,
    }
    paths = sorted((out_dir / "dram").glob("channel*/dramsim3.json"))
    if not paths:
        raise ValueError(f"no DRAMSim3 JSON found under {out_dir / 'dram'}")
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if len(payload) != 1:
            raise ValueError(f"expected one DRAM record in {path}")
        row = next(iter(payload.values()))
        totals["dram_channels"] += 1
        totals["dram_reads"] += int(row["num_reads_done"])
        totals["dram_writes"] += int(row["num_writes_done"])
        totals["dram_activates"] += int(row["num_act_cmds"])
        totals["dram_precharges"] += int(row["num_pre_cmds"])
        totals["dram_read_row_hits"] += int(row["num_read_row_hits"])
        totals["dram_write_row_hits"] += int(row["num_write_row_hits"])
        totals["dram_total_energy_pj"] += float(row["total_energy"])
    return totals


def validate_result(
    result: dict[str, Any], dram: dict[str, int | float], *, channels: int
) -> list[str]:
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_vertical",
        "correctness": result.get("correctness_mismatches") == 0,
        "frontier_correctness": result.get("frontier_mismatches") == 0,
        "frontier": result.get("next_active") == 10,
        "maintenance_passes": result.get("maintenance_scan_passes") == 20,
        "maintenance_visits": result.get("maintenance_edge_visits") == 200,
        "maintenance_bytes": result.get("maintenance_sorted_bytes") == 3_200,
        "maintenance_sorted_payload": result.get(
            "maintenance_sorted_payload_read_bytes"
        )
        == result.get("maintenance_sorted_bytes"),
        "maintenance_scan_ledger": maintenance_scan_ledger_matches(
            result,
            edges=10,
            unique_sources=1,
            family_precount_visits=160,
            l0_write_visits=10,
        ),
        "reader_tiles": result.get("reader_tiles") == 5,
        "reader_edges": result.get("reader_edges") == 10,
        "reader_bytes": result.get("reader_graph_bytes") == 184,
        "maintenance_graph_index_payload": result.get(
            "maintenance_graph_index_payload_write_bytes"
        )
        == 64,
        "maintenance_graph_payload": result.get(
            "maintenance_graph_payload_write_bytes"
        )
        == 80,
        "maintenance_page_list": result.get(
            "maintenance_page_list_payload_write_bytes"
        )
        == 8
        and result.get("maintenance_page_list_count_write_bytes") == 128,
        "reader_graph_index_payload": result.get(
            "reader_graph_index_payload_bytes"
        )
        == 24,
        "reader_graph_payload": result.get("reader_graph_payload_bytes") == 160,
        "reader_graph_payload_split": result.get(
            "reader_construction_payload_bytes"
        )
        == 80
        and result.get("reader_replay_payload_bytes") == 80,
        "reader_graph_index_bitmap": result.get(
            "reader_graph_index_bitmap_misses"
        )
        == 0,
        "reader_exact_range_path": result.get("reader_range_path") == 1
        and result.get("reader_range_error") == 0
        and result.get("reader_range_fallback_reason") == 0
        and result.get("reader_range_tasks") == 5
        and result.get("reader_range_level_checks") == 176
        and result.get("reader_range_construction_payloads") == 10
        and result.get("reader_range_replay_payloads") == 10,
        "reader_range_binning": result.get("reader_range_clear_cycles") == 256
        and result.get("reader_range_prefix_cycles") == 256
        and result.get("reader_range_scatter_cycles") == 5
        and result.get("reader_range_verify_cycles") == 256,
        "reader_metadata": result.get("reader_metadata_bytes") == 2_928,
        "reader_dirty_payload": result.get("reader_dirty_list_bytes") == 16
        and result.get("reader_dirty_bitmap_bytes") == 16
        and result.get("reader_active_bin_bytes") == 0,
        "reader_source_protocol": result.get("reader_source_requests") == 1
        and result.get("reader_source_responses") == 1
        and result.get("reader_source_windows") == 1
        and result.get("reader_protocol_markers") == 3
        and result.get("reader_protocol_acks") == 1
        and result.get("reader_protocol_status") == 0
        and result.get("reader_dirty_status") == 0
        and result.get("compute_protocol_markers") == 3
        and result.get("compute_protocol_acks") == 1
        and result.get("compute_protocol_status") == 0,
        "diagnostic_transcript": diagnostic_transcript_matches(result),
        "reader_epochs": result.get("reader_page_epoch_misses") == 0,
        "reader_levels": result.get("reader_occupied_levels") == 1,
        "compute_fast_tiles": result.get("compute_fast_tiles") == 5,
        "compute_no_full_tiles": result.get("compute_full_tiles") == 0,
        "compute_edges": result.get("compute_processed_edges") == 10,
        "axis_transfers": result.get("edge_axis_transfers") == 35
        and result.get("value_axis_transfers") == 2,
        "axis_capacity": 0 <= result.get("edge_axis_max_occupancy", -1) <= 32,
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def validate_carry_hot_result(
    result: dict[str, Any], dram: dict[str, int | float], *, channels: int
) -> list[str]:
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_vertical",
        "correctness": result.get("correctness_mismatches") == 0,
        "frontier_correctness": result.get("frontier_mismatches") == 0,
        "frontier": result.get("next_active") == 3,
        "input_shape": result.get("input_edges") == 2
        and result.get("preload_edges") == 1,
        "maintenance_targets": result.get("maintenance_target_level") == 1
        and result.get("maintenance_hot_target_level") == 0,
        "maintenance_timing": result.get("maintenance_cycles", 0) > 0
        and result.get("maintenance_end_cycle", 0)
        > result.get("maintenance_start_cycle", 0),
        "maintenance_partitioning": result.get("maintenance_cold_input_edges")
        == 1
        and result.get("maintenance_hot_input_edges") == 1,
        "maintenance_passes": result.get("maintenance_scan_passes") == 36,
        "maintenance_visits": result.get("maintenance_edge_visits") == 72,
        "maintenance_bytes": result.get("maintenance_sorted_bytes") == 1_184,
        "maintenance_sorted_payload": result.get(
            "maintenance_sorted_payload_read_bytes"
        )
        == result.get("maintenance_sorted_bytes"),
        "maintenance_scan_ledger": maintenance_scan_ledger_matches(
            result,
            edges=2,
            unique_sources=1,
            family_precount_visits=64,
            l0_write_visits=2,
        ),
        "carry_work": result.get("maintenance_carry_payload_reads") == 1
        and result.get("maintenance_carry_payload_read_bytes") == 8
        and result.get("maintenance_carry_new_batch_reads") == 2
        and result.get("maintenance_carry_new_batch_read_bytes") == 32
        and result.get("maintenance_carry_refill_wait_cycles", 0) > 0
        and result.get("maintenance_carry_cursor_metadata_read_bytes") == 96
        and result.get("maintenance_carry_cursor_page_ids") == 1
        and result.get("maintenance_carry_cursor_pages_visited") == 1
        and result.get("maintenance_carry_cursor_bitmap_words") == 4
        and result.get("maintenance_carry_cursor_bits_inspected") == 256
        and result.get("maintenance_carry_cursor_refill_cycles") == 261
        and result.get("maintenance_carry_cursor_rows_entered") == 1
        and result.get("maintenance_carry_cursor_row_offset_reads") == 2
        and result.get("maintenance_carry_cursor_validation_failures") == 0
        and result.get("maintenance_carry_writer_groups_seen") == 2
        and result.get("maintenance_carry_writer_groups_emitted") == 2
        and result.get("maintenance_carry_writer_groups_cancelled") == 0
        and result.get("maintenance_carry_writer_edge_word_writes") == 2
        and result.get("maintenance_carry_writer_row_word_writes") == 1
        and result.get("maintenance_carry_writer_mask_word_writes") == 1
        and result.get("maintenance_carry_writer_page_base_word_writes") == 2
        and result.get("maintenance_carry_writer_bitmap_page_writes") == 1
        and result.get("maintenance_carry_writer_page_list_word_writes") == 1
        and result.get("maintenance_carry_writer_page_epoch_word_writes") == 1
        and result.get("maintenance_carry_writer_memory_wait_cycles", 0) > 0
        and result.get("maintenance_carry_max_buffered_heads") == 2
        and result.get("maintenance_carry_merge_inputs") == 2
        and result.get("maintenance_carry_outputs") == 2,
        "reader_tiles": result.get("reader_tiles") == 1,
        "reader_edges": result.get("reader_edges") == 3,
        "reader_bytes": result.get("reader_graph_bytes") == 96,
        "maintenance_graph_index_payload": result.get(
            "maintenance_graph_index_payload_write_bytes"
        )
        == 128,
        "maintenance_graph_payload": result.get(
            "maintenance_graph_payload_write_bytes"
        )
        == 24,
        "maintenance_page_list": result.get(
            "maintenance_page_list_payload_write_bytes"
        )
        == 16
        and result.get("maintenance_page_list_count_write_bytes") == 320,
        "reader_graph_index_payload": result.get(
            "reader_graph_index_payload_bytes"
        )
        == 48,
        "reader_graph_payload": result.get("reader_graph_payload_bytes") == 48,
        "reader_graph_payload_split": result.get(
            "reader_construction_payload_bytes"
        )
        == 24
        and result.get("reader_replay_payload_bytes") == 24,
        "reader_graph_index_bitmap": result.get(
            "reader_graph_index_bitmap_misses"
        )
        == 0,
        "reader_exact_range_path": result.get("reader_range_path") == 1
        and result.get("reader_range_error") == 0
        and result.get("reader_range_fallback_reason") == 0
        and result.get("reader_range_tasks") == 2
        and result.get("reader_range_level_checks") == 352
        and result.get("reader_range_construction_payloads") == 3
        and result.get("reader_range_replay_payloads") == 3,
        "reader_metadata": result.get("reader_metadata_bytes") == 3_000,
        "reader_dirty_payload": result.get("reader_dirty_list_bytes") == 16
        and result.get("reader_dirty_bitmap_bytes") == 16
        and result.get("reader_active_bin_bytes") == 0,
        "reader_source_protocol": result.get("reader_source_requests") == 1
        and result.get("reader_source_responses") == 1
        and result.get("reader_source_windows") == 1
        and result.get("reader_protocol_markers") == 3
        and result.get("reader_protocol_acks") == 1
        and result.get("reader_protocol_status") == 0
        and result.get("reader_dirty_status") == 0
        and result.get("compute_protocol_markers") == 3
        and result.get("compute_protocol_acks") == 1
        and result.get("compute_protocol_status") == 0,
        "diagnostic_transcript": diagnostic_transcript_matches(result),
        "reader_epochs": result.get("reader_page_epoch_misses") == 0,
        "reader_levels": result.get("reader_occupied_levels") == 2,
        "reader_partitioning": result.get("reader_cold_edges") == 2
        and result.get("reader_hot_edges") == 1,
        "compute_fast_tiles": result.get("compute_fast_tiles") == 1,
        "compute_no_full_tiles": result.get("compute_full_tiles") == 0,
        "compute_edges": result.get("compute_processed_edges") == 3,
        "axis_transfers": result.get("edge_axis_transfers") == 20
        and result.get("value_axis_transfers") == 2,
        "axis_capacity": 0 <= result.get("edge_axis_max_occupancy", -1) <= 32,
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def validate_full_compute_result(
    result: dict[str, Any], dram: dict[str, int | float], *, channels: int
) -> list[str]:
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_compute",
        "correctness": result.get("correctness_mismatches") == 0,
        "frontier_correctness": result.get("frontier_mismatches") == 0,
        "frontier_size": result.get("next_active")
        == result.get("expected_frontier"),
        "real_slice_edges": result.get("input_edges") == 64_658,
        "tile_paths": result.get("compute_fast_tiles") == 11
        and result.get("compute_full_tiles") == 1,
        "processed_edges": result.get("compute_processed_edges") == 64_658,
        "vertex_read_payload": result.get("compute_vertex_payload_read_bytes")
        == result.get("compute_vertex_read_bytes"),
        "vertex_write_payload": result.get("compute_vertex_payload_write_bytes")
        == result.get("compute_vertex_write_bytes"),
        "tiny_gathers": result.get("compute_gathered_words") == 14_676,
        "full_sweep": result.get("compute_swept_words") == 2 * 65_536,
        "finite_buffer_replay": result.get("compute_full_buffer_replay_edges")
        == 4096,
        "threshold_crossing": result.get("compute_full_overflow_edges") == 1,
        "stream_tail": result.get("compute_full_stream_edges") == 45_885,
        "axis_transfers": result.get("edge_axis_transfers") == 64_683,
        "axis_capacity": result.get("edge_axis_max_occupancy") == 32,
        "axis_backpressure": result.get("edge_axis_push_stalls", 0) > 0,
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def validate_full_pagerank_result(
    result: dict[str, Any], dram: dict[str, int | float], *, channels: int
) -> list[str]:
    ranks = result.get("ranks", [])
    reference = result.get("reference_ranks", [])
    expected = [0.17, 0.21, 0.45, 0.17]
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_pagerank",
        "algorithm_timing_label": result.get("timing_evidence")
        == "provisional_algorithm_pipeline",
        "input_shape": result.get("vertices") == 4
        and result.get("input_edges") == 4,
        "iterations": result.get("pagerank_iterations", 0) > 0
        and result.get("pagerank_completed_iterations")
        == result.get("pagerank_iterations")
        and len(result.get("iteration_cycles", []))
        == result.get("pagerank_iterations")
        and all(cycles > 0 for cycles in result.get("iteration_cycles", [])),
        "correctness": result.get("correctness_mismatches") == 0
        and result.get("max_abs_error", 1.0) <= 1.0e-5
        and len(ranks) == len(reference) == 4
        and all(
            abs(actual - wanted) <= 1.0e-5
            for actual, wanted in zip(ranks, reference)
        )
        and abs(result.get("rank_sum", 0.0) - 1.0) <= 1.0e-5,
        "known_two_iteration_result": result.get("pagerank_iterations") != 2
        or all(
            abs(actual - wanted) <= 1.0e-5
            for actual, wanted in zip(ranks, expected)
        ),
        "maintenance_once": result.get("maintenance_persisted_edges") == 4
        and result.get("maintenance_cycles", 0) > 0,
        "reader": result.get("reader_edges") == 4
        and result.get("reader_graph_payload_bytes") == 64
        and result.get("reader_source_requests") == 4
        and result.get("reader_source_responses") == 4
        and result.get("reader_source_windows") == 1
        and result.get("reader_protocol_status") == 0,
        "compute": result.get("compute_edges") == 4
        and result.get("compute_vertices_applied") == 4
        and result.get("compute_memory_requests") == 16
        and result.get("source_map_operations") == 4
        and result.get("reduce_operations") == 8
        and result.get("apply_operations") == 4,
        "axis": result.get("edge_axis_transfers") == 24
        and result.get("value_axis_transfers") == 5,
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def validate_residual_pagerank_result(
    result: dict[str, Any], dram: dict[str, int | float], *, channels: int
) -> list[str]:
    frontier_in = result.get("frontier_in_sizes", [])
    frontier_out = result.get("frontier_out_sizes", [])
    requests = result.get("compute_requests_per_iteration", [])
    rounds = result.get("iterations", 0)
    frontier_shape_ok = (
        rounds > 0
        and len(frontier_in) == len(frontier_out) == rounds
        and frontier_in[0] == result.get("vertices")
        and frontier_out[-1] == 0
    )
    default_epsilon = abs(result.get("pagerank_epsilon", 0.0) - 1.0e-5) < 1.0e-12
    ledger_ok = (
        len(frontier_in) == len(frontier_out) == len(requests) == rounds
        and all(
            request_count == 5 * active_sources + 2 * result.get("vertices", 0)
            for active_sources, request_count in zip(
                frontier_in, requests, strict=True
            )
        )
    )
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_residual_pagerank",
        "algorithm_timing_label": result.get("timing_evidence")
        == "provisional_algorithm_pipeline",
        "input_shape": result.get("vertices") == 4
        and result.get("input_edges") == 4,
        "convergence": result.get("converged") is True
        and result.get("final_active") == 0
        and frontier_shape_ok,
        "known_default_frontier": not default_epsilon
        or (rounds == 49 and any(0 < size < 4 for size in frontier_in)),
        "correctness": result.get("correctness_mismatches") == 0
        and result.get("frontier_match") is True
        and result.get("max_abs_error", 1.0) <= 1.0e-5
        and result.get("residual_l1", 1.0)
        <= result.get("pagerank_epsilon", 0.0) * 1.01,
        "memory_ledger": result.get("memory_ledger_match") is True and ledger_ok,
        "maintenance_once": result.get("maintenance_persisted_edges") == 4
        and result.get("maintenance_cycles", 0) > 0,
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def validate_multiround_sssp_result(
    result: dict[str, Any], dram: dict[str, int | float], *, channels: int
) -> list[str]:
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_sssp",
        "converged": result.get("converged") is True,
        "correctness": result.get("correctness_mismatches") == 0,
        "frontier_correctness": result.get("frontier_mismatches") == 0,
        "input_shape": result.get("input_edges") == 8,
        "round_count": result.get("rounds") == 6,
        "final_values": result.get("final_values") == [0, 3, 2, 7, 8, 10],
        "frontier_inputs": result.get("frontier_in_sizes") == [1, 3, 2, 2, 2, 1],
        "frontier_outputs": result.get("frontier_out_sizes") == [3, 2, 2, 2, 1, 0],
        "round_edges": result.get("processed_edges_per_round") == [8, 3, 2, 2, 1, 0],
        "maintenance_once": result.get("maintenance_scan_passes") == 20
        and result.get("maintenance_edge_visits") == 160
        and result.get("maintenance_sorted_bytes") == 2_560,
        "maintenance_sorted_payload": result.get(
            "maintenance_sorted_payload_read_bytes"
        )
        == result.get("maintenance_sorted_bytes"),
        "maintenance_scan_ledger": maintenance_scan_ledger_matches(
            result,
            edges=8,
            unique_sources=5,
            family_precount_visits=128,
            l0_write_visits=8,
        ),
        "round_timing": len(result.get("round_cycles", [])) == 6
        and all(cycles > 0 for cycles in result.get("round_cycles", [])),
        "round_fifo": len(result.get("edge_axis_max_occupancy_per_round", []))
        == 6
        and all(
            0 <= occupancy <= 32
            for occupancy in result.get("edge_axis_max_occupancy_per_round", [])
        )
        and len(result.get("edge_axis_push_stalls_per_round", [])) == 6,
        "round_tile_paths": result.get("full_tiles_per_round") == [0] * 6
        and len(result.get("fast_tiles_per_round", [])) == 6,
        "round_metadata": len(result.get("reader_metadata_bytes_per_round", []))
        == 6
        and result.get("reader_metadata_bytes_per_round")
        == [2_960, 3_232, 3_232, 3_232, 3_224, 3_216],
        "dirty_ownership": result.get("reader_dirty_counts_per_round")
        == [5, 0, 0, 0, 0, 0]
        and result.get("reader_dirty_generations_per_round")
        == [1, 2, 2, 2, 2, 2]
        and result.get("reader_ack_eligible_per_round")
        == [1, 0, 0, 0, 0, 0]
        and result.get("reader_host_coverage_match_per_round") == [0] * 6
        and result.get("dirty_ack_started") == 1
        and result.get("dirty_ack_status") == 0
        and result.get("dirty_ack_captured_count") == 5
        and result.get("dirty_ack_captured_generation") == 1
        and result.get("dirty_ack_result_count") == 0
        and result.get("dirty_ack_result_generation") == 2
        and result.get("dirty_ack_candidate_write_bytes") == 40
        and result.get("dirty_ack_metadata_read_bytes") == 72
        and result.get("dirty_ack_metadata_write_bytes") == 64
        and result.get("dirty_ack_list_read_bytes") == 160
        and result.get("dirty_ack_bitmap_read_bytes") == 160
        and result.get("dirty_ack_bitmap_write_bytes") == 80
        and result.get("dirty_ack_validated_sources") == 5
        and result.get("dirty_ack_cleared_sources") == 5
        and result.get("dirty_ack_generation_advances") == 1
        and result.get("dirty_ack_cycles", 0) > 0,
        "round_active_protocol": result.get("reader_source_sizes_per_round")
        == [5, 2, 2, 2, 1, 0]
        and result.get("reader_source_requests_per_round") == [5, 0, 0, 0, 0, 0]
        and result.get("reader_source_responses_per_round")
        == [5, 0, 0, 0, 0, 0]
        and result.get("reader_source_windows_per_round") == [1, 0, 0, 0, 0, 0]
        and result.get("reader_protocol_markers_per_round")
        == [3, 0, 0, 0, 0, 0]
        and result.get("reader_protocol_acks_per_round") == [1, 0, 0, 0, 0, 0]
        and result.get("reader_protocol_status_per_round") == [0] * 6
        and result.get("reader_dirty_status_per_round") == [0] * 6
        and result.get("compute_protocol_status_per_round") == [0] * 6
        and result.get("reader_dirty_list_bytes_per_round") == [80, 0, 0, 0, 0, 0]
        and result.get("reader_dirty_bitmap_bytes_per_round")
        == [80, 0, 0, 0, 0, 0]
        and result.get("reader_active_bin_bytes_per_round")
        == [0, 64, 64, 64, 32, 0],
        "round_diagnostic_transcript": multiround_diagnostic_transcript_matches(
            result
        ),
        "round_epochs": result.get("reader_epoch_misses_per_round") == [0] * 6,
        "round_axis_protocol": result.get("edge_axis_transfers_per_round")
        == [29, 16, 15, 15, 14, 11]
        and result.get("value_axis_transfers_per_round") == [6, 0, 0, 0, 0, 0]
        and all(
            occupancy <= 32
            for occupancy in result.get("value_axis_max_occupancy_per_round", [])
        ),
        "maintenance_graph_payload": result.get(
            "maintenance_graph_payload_write_bytes"
        )
        == 64,
        "maintenance_graph_index_payload": result.get(
            "maintenance_graph_index_payload_write_bytes", 0
        )
        > 0,
        "maintenance_page_list": result.get(
            "maintenance_page_list_payload_write_bytes"
        )
        == 8
        and result.get("maintenance_page_list_count_write_bytes") == 128,
        "reader_graph_index_payload": result.get(
            "reader_graph_index_payload_bytes_per_round"
        )
        == [136, 56, 64, 56, 24, 0],
        "reader_graph_payload": result.get(
            "reader_graph_payload_bytes_per_round"
        )
        == [128, 48, 32, 32, 16, 0],
        "reader_graph_payload_split": result.get(
            "reader_construction_payload_bytes_per_round"
        )
        == [64, 24, 16, 16, 8, 0]
        and result.get("reader_replay_payload_bytes_per_round")
        == [64, 24, 16, 16, 8, 0],
        "reader_graph_index_bitmap": result.get(
            "reader_graph_index_bitmap_misses_per_round"
        )
        == [0, 0, 0, 0, 0, 0],
        "reader_range_tasks": result.get("reader_range_tasks_per_round")
        == [5, 2, 2, 2, 1, 0]
        and result.get("reader_range_row_lookups_per_round")
        == [5, 2, 2, 2, 1, 0]
        and result.get("reader_range_level_checks_per_round")
        == [880, 22, 22, 22, 11, 0],
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def validate_dynamic_sssp_result(
    result: dict[str, Any], dram: dict[str, int | float], *, channels: int
) -> list[str]:
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_sssp",
        "dynamic_mode": result.get("dynamic_update") is True,
        "update_path": result.get("dynamic_update_path") == "incremental_relax"
        and result.get("materialized_snapshot_edges") == 5,
        "cold_correctness": result.get("cold_correctness_mismatches") == 0
        and result.get("cold_frontier_mismatches") == 0
        and result.get("cold_final_values") == [0, 5, 10, 11],
        "update_correctness": result.get("correctness_mismatches") == 0
        and result.get("full_recompute_correctness_mismatches") == 0
        and result.get("frontier_mismatches") == 0
        and result.get("final_values") == [0, 5, 2, 3],
        "input_shape": result.get("input_edges") == 4
        and result.get("update_edges") == 1,
        "cold_lifecycle": result.get("cold_rounds") == 4
        and result.get("cold_maintenance_target_level") == 0
        and result.get("cold_dirty_generation_after_ack") == 2
        and result.get("cold_cycles", 0) > 0
        and result.get("cold_maintenance_cycles", 0) > 0
        and len(result.get("cold_round_cycles", [])) == 4
        and all(cycle > 0 for cycle in result.get("cold_round_cycles", [])),
        "update_lifecycle": result.get("rounds") == 3
        and result.get("maintenance_target_level") == 1
        and result.get("maintenance_persisted_edges") == 4
        and result.get("maintenance_dirty_generation") == 3
        and result.get("dirty_ack_captured_generation") == 3
        and result.get("dirty_ack_result_generation") == 4
        and result.get("update_cycles", 0) > 0,
        "update_frontier": result.get("frontier_in_sizes") == [1, 1, 1]
        and result.get("frontier_out_sizes") == [1, 1, 0]
        and result.get("processed_edges_per_round") == [2, 1, 0]
        and result.get("reader_dirty_counts_per_round") == [1, 0, 0]
        and result.get("reader_dirty_generations_per_round") == [3, 4, 4],
        "update_maintenance": result.get("maintenance_scan_passes") == 19
        and result.get("maintenance_edge_visits") == 19
        and result.get("maintenance_carry_new_batch_reads") == 1
        and result.get("maintenance_carry_new_batch_read_bytes") == 16
        and result.get("maintenance_sorted_bytes")
        == result.get("maintenance_edge_visits", 0) * 16
        + result.get("maintenance_carry_new_batch_read_bytes", 0)
        and result.get("maintenance_sorted_payload_read_bytes")
        == result.get("maintenance_sorted_bytes")
        and result.get("maintenance_dirty_count") == 1
        and result.get("maintenance_dirty_unique_sources") == 1,
        "backend_segments": result.get("cold_backend_requests", 0) > 0
        and result.get("update_backend_requests", 0) > 0
        and result.get("cold_backend_requests", 0)
        + result.get("update_backend_requests", 0)
        == result.get("backend_requests"),
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def validate_nonmonotonic_sssp_result(
    result: dict[str, Any],
    dram: dict[str, int | float],
    *,
    channels: int,
    expected_values: list[int],
    expected_update_edges: int,
    expected_snapshot_edges: int,
    expected_dirty_sources: int,
    expected_rounds: int,
    expected_frontier_in: list[int],
    expected_frontier_out: list[int],
) -> list[str]:
    expected_scan_visits = 20 * expected_snapshot_edges
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_sssp",
        "update_path": result.get("dynamic_update") is True
        and result.get("dynamic_update_path") == "full_rebuild"
        and result.get("update_edges") == expected_update_edges
        and result.get("materialized_snapshot_edges")
        == expected_snapshot_edges,
        "cold_correctness": result.get("cold_correctness_mismatches") == 0
        and result.get("cold_frontier_mismatches") == 0
        and result.get("cold_final_values") == [0, 5, 10, 11],
        "update_correctness": result.get("correctness_mismatches") == 0
        and result.get("full_recompute_correctness_mismatches") == 0
        and result.get("frontier_mismatches") == 0
        and result.get("final_values") == expected_values,
        "full_rebuild_metadata": result.get("maintenance_target_level") == 0
        and result.get("maintenance_full_rebuild_clear_requests") == 3
        and result.get("maintenance_full_rebuild_clear_bytes") == 25_344
        and result.get("maintenance_full_rebuild_clear_cycles", 0) > 0,
        "full_recompute_vertex_state": result.get(
            "compute_full_recompute_reset_words"
        )
        == 4
        and result.get("compute_full_recompute_reset_write_bytes") == 16
        and result.get("compute_full_recompute_reset_cycles", 0) > 0,
        "update_lifecycle": result.get("rounds") == expected_rounds
        and result.get("maintenance_persisted_edges")
        == expected_snapshot_edges
        and result.get("maintenance_dirty_generation") == 3
        and result.get("dirty_ack_captured_generation") == 3
        and result.get("dirty_ack_result_generation") == 4
        and result.get("update_cycles", 0) > 0,
        "update_frontier": result.get("frontier_in_sizes")
        == expected_frontier_in
        and result.get("frontier_out_sizes") == expected_frontier_out,
        "maintenance_ledger": result.get("maintenance_scan_passes") == 20
        and result.get("maintenance_edge_visits") == expected_scan_visits
        and result.get("maintenance_sorted_bytes")
        == expected_scan_visits * 16
        and result.get("maintenance_sorted_payload_read_bytes")
        == result.get("maintenance_sorted_bytes")
        and result.get("maintenance_carry_new_batch_reads") == 0
        and result.get("maintenance_carry_new_batch_read_bytes") == 0
        and result.get("maintenance_dirty_count") == expected_dirty_sources
        and result.get("maintenance_dirty_unique_sources")
        == expected_dirty_sources,
        "backend_segments": result.get("cold_backend_requests", 0) > 0
        and result.get("update_backend_requests", 0) > 0
        and result.get("cold_backend_requests", 0)
        + result.get("update_backend_requests", 0)
        == result.get("backend_requests"),
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def validate_protocol_window_result(
    result: dict[str, Any], dram: dict[str, int | float], *, channels: int
) -> list[str]:
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_vertical",
        "correctness": result.get("correctness_mismatches") == 0
        and result.get("frontier_mismatches") == 0,
        "input_shape": result.get("input_edges") == 17
        and result.get("next_active") == 1,
        "reader_protocol": result.get("reader_source_requests") == 17
        and result.get("reader_source_responses") == 17
        and result.get("reader_source_windows") == 2
        and result.get("reader_protocol_markers") == 3
        and result.get("reader_protocol_acks") == 1
        and result.get("reader_protocol_status") == 0
        and result.get("reader_dirty_status") == 0,
        "compute_protocol": result.get("compute_protocol_markers") == 3
        and result.get("compute_protocol_acks") == 1
        and result.get("compute_protocol_status") == 0,
        "diagnostic_transcript": diagnostic_transcript_matches(result),
        "axis_transcript": result.get("edge_axis_transfers") == 50
        and result.get("value_axis_transfers") == 18
        and 1 < result.get("edge_axis_max_occupancy", 0) <= 32
        and 0 < result.get("value_axis_max_occupancy", 0) <= 32,
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def validate_fallback_result(
    result: dict[str, Any],
    dram: dict[str, int | float],
    *,
    channels: int,
    expected_reason: int,
) -> list[str]:
    values = result.get("final_values", [])
    full_values_ok = (
        isinstance(values, list)
        and len(values) == 131_073
        and values[0] == 0
        and values[1] == 1
        and values[65_536] == 2
        and values[131_072] == 3
    )
    compact_values_ok = (
        result.get("final_values_count") == 131_073
        and result.get("final_value_samples")
        == {"0": 0, "1": 1, "65536": 2, "131072": 3}
        and isinstance(result.get("final_values_sha256"), str)
        and len(result["final_values_sha256"]) == 64
    )
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_sssp",
        "converged": result.get("converged") is True,
        "correctness": result.get("correctness_mismatches") == 0
        and result.get("frontier_mismatches") == 0,
        "input_shape": result.get("input_edges") == 3
        and result.get("rounds") == 2,
        "selected_values": full_values_ok or compact_values_ok,
        "logical_work": result.get("processed_edges_per_round") == [3, 0]
        and result.get("frontier_in_sizes") == [1, 3]
        and result.get("frontier_out_sizes") == [3, 0],
        "accepted_fallback": result.get("reader_range_paths_per_round")
        == [2, 1]
        and result.get("reader_range_fallback_reasons_per_round")
        == [expected_reason, 0]
        and result.get("compute_range_paths_per_round") == [2, 1]
        and result.get("compute_range_fallback_reasons_per_round")
        == [expected_reason, 0]
        and result.get("reader_range_errors_per_round") == [0, 0]
        and result.get("compute_range_errors_per_round") == [0, 0],
        "fallback_work": result.get("reader_fallback_partitions_per_round")
        == [1, 0]
        and result.get("reader_fallback_forced_dense_partitions_per_round")
        == [0, 0]
        and result.get("reader_fallback_active_record_reads_per_round")
        == [4, 0]
        and result.get("reader_fallback_row_lookups_per_round") == [4, 0]
        and result.get("reader_fallback_replay_edges_per_round") == [3, 0],
        "handoff_visible": result.get("host_handoffs") == 1
        and result.get("host_handoff_logical_rounds") == [0]
        and result.get("host_handoff_reasons") == [expected_reason]
        and result.get("host_handoff_source_counts") == [1]
        and result.get("host_handoff_list_read_bytes") == [16]
        and result.get("host_handoff_control_cycles") == [0]
        and result.get("host_handoff_control_timed") == [0]
        and result.get("host_handoff_device_reader_overflow") == [1]
        and result.get("host_handoff_device_compute_overflow") == [1]
        and result.get("host_handoff_device_attempt_cycles", [0])[0] > 0,
        "attempt_included_in_round": result.get("round_cycles", [0])[0]
        > result.get("host_handoff_device_attempt_cycles", [0])[0],
        "diagnostic_transcript": multiround_diagnostic_transcript_matches(result),
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument("--profile", type=Path, default=PROFILE_PATH)
    parser.add_argument(
        "--validation-mode",
        choices=("fixture", "generic"),
        default="fixture",
    )
    parser.add_argument("--max-cycles", type=int)
    parser.add_argument("--max-rounds", type=int, default=256)
    parser.add_argument(
        "--scenario",
        choices=(
            "amazon_l0",
            "carry_hot",
            "amazon_full_compute",
            "full_pagerank",
            "residual_pagerank",
            "weighted_sssp",
            "dynamic_sssp",
            "dynamic_sssp_delete",
            "dynamic_sssp_increase",
            "protocol_window",
            "fallback_capacity",
            "fallback_payload",
            "candidate10_maintenance",
        ),
        default="amazon_l0",
    )
    parser.add_argument("--preload", type=Path)
    parser.add_argument("--update-workload", type=Path)
    parser.add_argument("--hot-vertices", default="")
    parser.add_argument("--source", type=int)
    parser.add_argument("--pagerank-iterations", type=int, default=2)
    parser.add_argument("--pagerank-damping", type=float, default=0.8)
    parser.add_argument("--pagerank-epsilon", type=float, default=1.0e-5)
    parser.add_argument(
        "--residual-contract",
        choices=(
            "generic_dangling_l1_cold",
            "deltahls_sink_free_linf_warm",
        ),
        default="generic_dangling_l1_cold",
    )
    parser.add_argument("--residual-max-iterations", type=int, default=256)
    parser.add_argument("--pagerank-source-latency", type=int, default=3)
    parser.add_argument("--pagerank-source-ii", type=int, default=1)
    parser.add_argument("--pagerank-source-capacity", type=int, default=4)
    parser.add_argument("--pagerank-edge-latency", type=int, default=1)
    parser.add_argument("--pagerank-edge-ii", type=int, default=1)
    parser.add_argument("--pagerank-edge-capacity", type=int, default=4)
    parser.add_argument("--pagerank-reduce-latency", type=int, default=2)
    parser.add_argument("--pagerank-reduce-ii", type=int, default=1)
    parser.add_argument("--pagerank-reduce-capacity", type=int, default=8)
    parser.add_argument("--pagerank-apply-latency", type=int, default=3)
    parser.add_argument("--pagerank-apply-ii", type=int, default=1)
    parser.add_argument("--pagerank-apply-capacity", type=int, default=8)
    parser.add_argument("--channels", type=int, default=32)
    parser.add_argument("--device-dirty-source-limit", type=int, default=4_096)
    parser.add_argument("--range-task-active-gate", type=int)
    parser.add_argument("--range-task-capacity", type=int, default=65_536)
    parser.add_argument(
        "--range-task-payload-budget", type=int, default=1_048_576
    )
    parser.add_argument("--fallback-replay-threshold", type=int, default=65_536)
    parser.add_argument(
        "--fallback-level-cache-reuse",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="reuse launch-loaded level metadata during HOST fallback",
    )
    parser.add_argument(
        "--source-page-index-cache",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable the finite per-family/level source-page index cache",
    )
    parser.add_argument(
        "--memory-request-window",
        type=int,
        default=1,
        help=(
            "logical parent-request window per AXI initiator; one preserves "
            "same-port ordering while independent HLS bundles may overlap, "
            "and values above one are a same-port architecture what-if"
        ),
    )
    parser.add_argument(
        "--compute-memory-request-window",
        type=int,
        default=7,
        help="bounded HLS parent-request credits for compute AXI traffic",
    )
    parser.add_argument(
        "--compute-writeonly-request-window",
        type=int,
        default=4,
        help="bounded HLS parent-request credits for write-only compute ports",
    )
    parser.add_argument("--compute-tiny-bram-read-latency", type=int, default=2)
    parser.add_argument("--compute-vs-uram-read-latency", type=int, default=2)
    parser.add_argument(
        "--compute-active-bram-read-latency", type=int, default=2
    )
    parser.add_argument(
        "--compute-onchip-pipeline-capacity", type=int, default=4
    )
    parser.add_argument("--compute-vs-bypass-depth", type=int, default=4)
    parser.add_argument("--reader-edge-pipeline-depth", type=int, default=32)
    parser.add_argument("--reader-edge-response-capacity", type=int, default=32)
    parser.add_argument("--maintenance-count-scan-ii", type=int, default=1)
    parser.add_argument(
        "--maintenance-count-scan-tail-cycles", type=int, default=19
    )
    parser.add_argument("--maintenance-l0-write-scan-ii", type=int, default=24)
    parser.add_argument(
        "--maintenance-l0-write-scan-tail-cycles", type=int, default=42
    )
    parser.add_argument("--candidate-l0-precount-ii", type=int, default=1)
    parser.add_argument(
        "--candidate-l0-precount-tail-cycles", type=int, default=77
    )
    parser.add_argument("--candidate-l0-write-scan-ii", type=int, default=24)
    parser.add_argument(
        "--candidate-l0-write-scan-tail-cycles", type=int, default=149
    )
    parser.add_argument(
        "--candidate-l0-writer-rtl-schedule",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--candidate-l0-writer-base-residual-cycles", type=int, default=701
    )
    parser.add_argument(
        "--candidate-l0-writer-single-record-cycles", type=int, default=799
    )
    parser.add_argument(
        "--candidate-l0-writer-late-source-cycles", type=int, default=71
    )
    parser.add_argument(
        "--candidate-l0-writer-packer-cycles", type=int, default=69
    )
    parser.add_argument(
        "--candidate-l0-writer-page-tail-cycles", type=int, default=144
    )
    parser.add_argument(
        "--candidate-list-word-first-lane-cycles", type=int, default=81
    )
    parser.add_argument(
        "--candidate-list-word-additional-lane-cycles", type=int, default=120
    )
    parser.add_argument("--candidate-publication-base-cycles", type=int, default=229)
    parser.add_argument("--candidate-publication-source-cycles", type=int, default=5)
    parser.add_argument("--candidate-publication-group-cycles", type=int, default=20)
    parser.add_argument("--candidate-publication-new-bit-cycles", type=int, default=2)
    parser.add_argument(
        "--candidate-publication-prefetch-restart-cycles", type=int, default=72
    )
    parser.add_argument(
        "--candidate-publication-empty-base-cycles", type=int, default=156
    )
    parser.add_argument(
        "--candidate-publication-empty-group-cycles", type=int, default=9
    )
    parser.add_argument(
        "--candidate-publication-full-window-rebate-cycles", type=int, default=4
    )
    parser.add_argument(
        "--candidate-publication-next-window-overlap-cycles", type=int, default=3
    )
    parser.add_argument(
        "--maintenance-scan-response-capacity", type=int, default=32
    )
    parser.add_argument(
        "--axi-profile",
        choices=(
            "hls_split_9c08763",
            "candidate10_gmem_1e61fc0",
            "legacy_uniform64",
        ),
    )
    parser.add_argument(
        "--maintenance-architecture",
        choices=("shared_engine_serial", "candidate10_one_pass"),
        help="override the maintenance architecture selected by the profile",
    )
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument(
        "--instantiate-all-hbm-channels",
        action="store_true",
        help="instantiate idle SST HBM controllers for equivalence or energy runs",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile_path = args.profile.resolve()
    profile_bytes = profile_path.read_bytes()
    profile = json.loads(profile_bytes)
    if profile.get("architecture") != "spine":
        raise SystemExit("profile must describe the Spine architecture")
    profile_maintenance_architecture = profile.get("parameters", {}).get(
        "maintenance_architecture", "shared_engine_serial"
    )
    profile_axi = profile.get("parameters", {}).get(
        "axi_profile", "hls_split_9c08763"
    )
    profile_fallback_level_cache_reuse = bool(
        profile.get("parameters", {}).get("fallback_level_cache_reuse", False)
    )
    profile_source_page_index_cache = bool(
        profile.get("parameters", {}).get("source_page_index_cache", False)
    )
    profile_range_task_active_gate = int(
        profile.get("parameters", {}).get(
            "range_task_active_gate", 16_384
        )
    )
    if profile_range_task_active_gate <= 0:
        raise SystemExit("profile range_task_active_gate must be positive")
    if profile_axi not in {
        "hls_split_9c08763",
        "candidate10_gmem_1e61fc0",
        "legacy_uniform64",
    }:
        raise SystemExit("profile has an unknown axi_profile")
    if args.axi_profile is None:
        args.axi_profile = profile_axi
    if profile_maintenance_architecture not in {
        "shared_engine_serial",
        "candidate10_one_pass",
    }:
        raise SystemExit("profile has an unknown maintenance_architecture")
    if args.maintenance_architecture is None:
        args.maintenance_architecture = profile_maintenance_architecture
    if args.fallback_level_cache_reuse is None:
        args.fallback_level_cache_reuse = profile_fallback_level_cache_reuse
    if args.source_page_index_cache is None:
        args.source_page_index_cache = profile_source_page_index_cache
    if args.range_task_active_gate is None:
        args.range_task_active_gate = profile_range_task_active_gate
    try:
        data_clock = next(
            clock for clock in profile["clocks"] if clock["name"] == "data"
        )
        core_mhz = float(data_clock["achieved_mhz"])
    except (KeyError, StopIteration, TypeError, ValueError) as error:
        raise SystemExit("profile lacks an achieved Spine data clock") from error
    if args.source is None:
        args.source = 2 if args.scenario == "amazon_l0" else 0
    if args.scenario == "carry_hot":
        if args.workload == DEFAULT_WORKLOAD:
            args.workload = DEFAULT_CARRY_WORKLOAD
        if args.preload is None:
            args.preload = DEFAULT_CARRY_PRELOAD
        if not args.hot_vertices:
            args.hot_vertices = "17"
    elif (
        args.scenario == "amazon_full_compute"
        and args.workload == DEFAULT_WORKLOAD
    ):
        args.workload = DEFAULT_FULL_WORKLOAD
    elif args.scenario == "weighted_sssp" and args.workload == DEFAULT_WORKLOAD:
        args.workload = DEFAULT_SSSP_WORKLOAD
    elif args.scenario == "dynamic_sssp":
        if args.workload == DEFAULT_WORKLOAD:
            args.workload = DEFAULT_DYNAMIC_SSSP_WORKLOAD
        if args.update_workload is None:
            args.update_workload = DEFAULT_DYNAMIC_SSSP_UPDATE
    elif args.scenario in {"dynamic_sssp_delete", "dynamic_sssp_increase"}:
        if args.workload == DEFAULT_WORKLOAD:
            args.workload = DEFAULT_NONMONOTONIC_SSSP_WORKLOAD
        if args.update_workload is None:
            args.update_workload = (
                DEFAULT_DELETE_SSSP_UPDATE
                if args.scenario == "dynamic_sssp_delete"
                else DEFAULT_INCREASE_SSSP_UPDATE
            )
    elif args.scenario in {"full_pagerank", "residual_pagerank"} and (
        args.workload == DEFAULT_WORKLOAD
    ):
        args.workload = DEFAULT_PAGERANK_WORKLOAD
    elif args.scenario == "protocol_window" and args.workload == DEFAULT_WORKLOAD:
        args.workload = DEFAULT_PROTOCOL_WORKLOAD
    elif args.scenario in {"fallback_capacity", "fallback_payload"}:
        if args.workload == DEFAULT_WORKLOAD:
            args.workload = DEFAULT_FALLBACK_WORKLOAD
        if (
            args.scenario == "fallback_capacity"
            and args.range_task_capacity == 65_536
        ):
            args.range_task_capacity = 2
        if (
            args.scenario == "fallback_payload"
            and args.range_task_payload_budget == 1_048_576
        ):
            args.range_task_payload_budget = 2
    if args.channels < 23 or args.source < 0 or not args.workload.is_file():
        raise SystemExit("channels must be >=23, source non-negative, workload present")
    if (
        args.maintenance_count_scan_ii <= 0
        or args.maintenance_l0_write_scan_ii <= 0
        or args.candidate_l0_precount_ii <= 0
        or args.candidate_l0_write_scan_ii <= 0
        or args.candidate_l0_writer_base_residual_cycles <= 0
        or args.candidate_l0_writer_single_record_cycles <= 0
        or args.candidate_l0_writer_late_source_cycles <= 0
        or args.candidate_l0_writer_packer_cycles <= 0
        or args.candidate_l0_writer_page_tail_cycles <= 0
        or args.candidate_list_word_first_lane_cycles <= 0
        or args.candidate_publication_base_cycles <= 0
        or args.candidate_publication_source_cycles <= 0
        or args.candidate_publication_group_cycles <= 0
        or args.candidate_publication_empty_base_cycles <= 0
        or args.candidate_publication_empty_group_cycles <= 0
        or args.compute_memory_request_window <= 0
        or args.compute_writeonly_request_window <= 0
        or args.compute_tiny_bram_read_latency <= 0
        or args.compute_vs_uram_read_latency <= 0
        or args.compute_active_bram_read_latency <= 0
        or args.compute_onchip_pipeline_capacity <= 0
        or args.compute_vs_bypass_depth <= 0
        or args.pagerank_iterations <= 0
        or not 0.0 < args.pagerank_damping < 1.0
        or args.pagerank_epsilon <= 0.0
        or args.residual_max_iterations <= 0
        or args.pagerank_source_latency <= 0
        or args.pagerank_source_ii <= 0
        or args.pagerank_source_capacity <= 0
        or args.pagerank_edge_latency <= 0
        or args.pagerank_edge_ii <= 0
        or args.pagerank_edge_capacity <= 0
        or args.pagerank_reduce_latency <= 0
        or args.pagerank_reduce_ii <= 0
        or args.pagerank_reduce_capacity <= 0
        or args.pagerank_apply_latency <= 0
        or args.pagerank_apply_ii <= 0
        or args.pagerank_apply_capacity <= 0
        or args.maintenance_count_scan_tail_cycles < 0
        or args.maintenance_l0_write_scan_tail_cycles < 0
        or args.candidate_l0_precount_tail_cycles < 0
        or args.candidate_l0_write_scan_tail_cycles < 0
        or args.candidate_list_word_additional_lane_cycles < 0
        or args.candidate_publication_new_bit_cycles < 0
        or args.candidate_publication_prefetch_restart_cycles < 0
        or args.candidate_publication_full_window_rebate_cycles < 0
        or args.candidate_publication_next_window_overlap_cycles < 0
        or args.maintenance_scan_response_capacity <= 0
        or args.max_rounds <= 0
        or (args.max_cycles is not None and args.max_cycles <= 0)
    ):
        raise SystemExit("maintenance scan IIs must be positive and tails non-negative")
    if args.preload is not None and not args.preload.is_file():
        raise SystemExit(f"preload workload is missing: {args.preload}")
    if args.update_workload is not None and not args.update_workload.is_file():
        raise SystemExit(f"update workload is missing: {args.update_workload}")
    generic_scenarios = {
        "weighted_sssp",
        "dynamic_sssp",
        "dynamic_sssp_delete",
        "dynamic_sssp_increase",
        "full_pagerank",
        "residual_pagerank",
    }
    if args.validation_mode == "generic" and args.scenario not in (
        generic_scenarios | {"candidate10_maintenance"}
    ):
        raise SystemExit("generic validation supports only shared algorithm scenarios")
    workload_vertices, workload_edges = load_slice_shape(args.workload)
    update_edges = (
        0
        if args.update_workload is None
        else load_slice_shape(args.update_workload)[1]
    )
    hot_vertices = tuple(
        int(item) for item in args.hot_vertices.split(",") if item
    )
    binding_paths = [args.workload]
    if args.preload is not None:
        binding_paths.append(args.preload)
    if args.update_workload is not None:
        binding_paths.append(args.update_workload)
    binding = spine_memory_binding(
        profile,
        binding_paths,
        hot_vertices=hot_vertices,
        physical_channels=args.channels,
        instantiate_all=args.instantiate_all_hbm_channels,
    )
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst"], cwd=ROOT, check=True)
    library = args.lib_dir / "libspine_cycle.so"
    if not library.is_file():
        raise SystemExit(f"missing SST element library: {library}")
    sst_library = forced_sst_library_binding(args.sst, args.lib_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.out_dir / "result.json"
    result_path.unlink(missing_ok=True)
    shutil.rmtree(args.out_dir / "dram", ignore_errors=True)
    env = os.environ.copy()
    env.update(
        {
            "SPINE_SST_CHANNELS": str(args.channels),
            "SPINE_SST_ACTIVE_CHANNELS": ",".join(
                str(channel) for channel in binding.instantiated_channels
            ),
            "SPINE_SST_MODE": {
                "amazon_full_compute": "spine_compute",
                "full_pagerank": "spine_pagerank",
                "residual_pagerank": "spine_residual_pagerank",
                "weighted_sssp": "spine_sssp",
                "dynamic_sssp": "spine_sssp",
                "dynamic_sssp_delete": "spine_sssp",
                "dynamic_sssp_increase": "spine_sssp",
                "fallback_capacity": "spine_sssp",
                "fallback_payload": "spine_sssp",
                "candidate10_maintenance": "spine_maintenance",
            }.get(args.scenario, "spine_vertical"),
            "SPINE_SST_WORKLOAD": str(args.workload.resolve()),
            "SPINE_SST_UPDATE_WORKLOAD": ""
            if args.update_workload is None
            else str(args.update_workload.resolve()),
            "SPINE_SST_SOURCE": str(args.source),
            "SPINE_SST_PRELOAD": ""
            if args.preload is None
            else str(args.preload.resolve()),
            "SPINE_SST_HOT_VERTICES": args.hot_vertices,
            "SPINE_SST_OUTPUT": str(result_path),
            "SPINE_SST_DRAM_OUTPUT": str(args.out_dir / "dram"),
            "SPINE_SST_CORE_MHZ": str(core_mhz),
            "SPINE_SST_MAX_CYCLES": str(
                args.max_cycles
                if args.max_cycles is not None
                else 5_000_000
                if args.scenario == "amazon_full_compute"
                else 1_000_000
            ),
            "SPINE_SST_MAX_ROUNDS": str(args.max_rounds),
            "SPINE_SST_PAGERANK_ITERATIONS": str(args.pagerank_iterations),
            "SPINE_SST_PAGERANK_DAMPING": str(args.pagerank_damping),
            "SPINE_SST_PAGERANK_EPSILON": str(args.pagerank_epsilon),
            "SPINE_SST_RESIDUAL_CONTRACT": args.residual_contract,
            "SPINE_SST_RESIDUAL_MAX_ITERATIONS": str(
                args.residual_max_iterations
            ),
            "SPINE_SST_PAGERANK_SOURCE_LATENCY": str(
                args.pagerank_source_latency
            ),
            "SPINE_SST_PAGERANK_SOURCE_II": str(args.pagerank_source_ii),
            "SPINE_SST_PAGERANK_SOURCE_CAPACITY": str(
                args.pagerank_source_capacity
            ),
            "SPINE_SST_PAGERANK_EDGE_LATENCY": str(args.pagerank_edge_latency),
            "SPINE_SST_PAGERANK_EDGE_II": str(args.pagerank_edge_ii),
            "SPINE_SST_PAGERANK_EDGE_CAPACITY": str(args.pagerank_edge_capacity),
            "SPINE_SST_PAGERANK_REDUCE_LATENCY": str(
                args.pagerank_reduce_latency
            ),
            "SPINE_SST_PAGERANK_REDUCE_II": str(args.pagerank_reduce_ii),
            "SPINE_SST_PAGERANK_REDUCE_CAPACITY": str(
                args.pagerank_reduce_capacity
            ),
            "SPINE_SST_PAGERANK_APPLY_LATENCY": str(
                args.pagerank_apply_latency
            ),
            "SPINE_SST_PAGERANK_APPLY_II": str(args.pagerank_apply_ii),
            "SPINE_SST_PAGERANK_APPLY_CAPACITY": str(
                args.pagerank_apply_capacity
            ),
            "SPINE_SST_DEVICE_DIRTY_SOURCE_LIMIT": str(
                args.device_dirty_source_limit
            ),
            "SPINE_SST_RANGE_TASK_ACTIVE_GATE": str(args.range_task_active_gate),
            "SPINE_SST_RANGE_TASK_CAPACITY": str(args.range_task_capacity),
            "SPINE_SST_RANGE_TASK_PAYLOAD_BUDGET": str(
                args.range_task_payload_budget
            ),
            "SPINE_SST_FALLBACK_REPLAY_THRESHOLD": str(
                args.fallback_replay_threshold
            ),
            "SPINE_SST_FALLBACK_LEVEL_CACHE_REUSE": (
                "1" if args.fallback_level_cache_reuse else "0"
            ),
            "SPINE_SST_SOURCE_PAGE_INDEX_CACHE": (
                "1" if args.source_page_index_cache else "0"
            ),
            "SPINE_SST_MEMORY_REQUEST_WINDOW": str(args.memory_request_window),
            "SPINE_SST_COMPUTE_MEMORY_REQUEST_WINDOW": str(
                args.compute_memory_request_window
            ),
            "SPINE_SST_COMPUTE_WRITEONLY_REQUEST_WINDOW": str(
                args.compute_writeonly_request_window
            ),
            "SPINE_SST_COMPUTE_TINY_BRAM_READ_LATENCY": str(
                args.compute_tiny_bram_read_latency
            ),
            "SPINE_SST_COMPUTE_VS_URAM_READ_LATENCY": str(
                args.compute_vs_uram_read_latency
            ),
            "SPINE_SST_COMPUTE_ACTIVE_BRAM_READ_LATENCY": str(
                args.compute_active_bram_read_latency
            ),
            "SPINE_SST_COMPUTE_ONCHIP_PIPELINE_CAPACITY": str(
                args.compute_onchip_pipeline_capacity
            ),
            "SPINE_SST_COMPUTE_VS_BYPASS_DEPTH": str(
                args.compute_vs_bypass_depth
            ),
            "SPINE_SST_READER_EDGE_PIPELINE_DEPTH": str(
                args.reader_edge_pipeline_depth
            ),
            "SPINE_SST_READER_EDGE_RESPONSE_CAPACITY": str(
                args.reader_edge_response_capacity
            ),
            "SPINE_SST_MAINTENANCE_COUNT_SCAN_II": str(
                args.maintenance_count_scan_ii
            ),
            "SPINE_SST_MAINTENANCE_COUNT_SCAN_TAIL_CYCLES": str(
                args.maintenance_count_scan_tail_cycles
            ),
            "SPINE_SST_MAINTENANCE_L0_WRITE_SCAN_II": str(
                args.maintenance_l0_write_scan_ii
            ),
            "SPINE_SST_MAINTENANCE_L0_WRITE_SCAN_TAIL_CYCLES": str(
                args.maintenance_l0_write_scan_tail_cycles
            ),
            "SPINE_SST_CANDIDATE_L0_PRECOUNT_II": str(
                args.candidate_l0_precount_ii
            ),
            "SPINE_SST_CANDIDATE_L0_PRECOUNT_TAIL_CYCLES": str(
                args.candidate_l0_precount_tail_cycles
            ),
            "SPINE_SST_CANDIDATE_L0_WRITE_SCAN_II": str(
                args.candidate_l0_write_scan_ii
            ),
            "SPINE_SST_CANDIDATE_L0_WRITE_SCAN_TAIL_CYCLES": str(
                args.candidate_l0_write_scan_tail_cycles
            ),
            "SPINE_SST_CANDIDATE_L0_WRITER_RTL_SCHEDULE": str(
                int(args.candidate_l0_writer_rtl_schedule)
            ),
            "SPINE_SST_CANDIDATE_L0_WRITER_BASE_RESIDUAL_CYCLES": str(
                args.candidate_l0_writer_base_residual_cycles
            ),
            "SPINE_SST_CANDIDATE_L0_WRITER_SINGLE_RECORD_CYCLES": str(
                args.candidate_l0_writer_single_record_cycles
            ),
            "SPINE_SST_CANDIDATE_L0_WRITER_LATE_SOURCE_CYCLES": str(
                args.candidate_l0_writer_late_source_cycles
            ),
            "SPINE_SST_CANDIDATE_L0_WRITER_PACKER_CYCLES": str(
                args.candidate_l0_writer_packer_cycles
            ),
            "SPINE_SST_CANDIDATE_L0_WRITER_PAGE_TAIL_CYCLES": str(
                args.candidate_l0_writer_page_tail_cycles
            ),
            "SPINE_SST_CANDIDATE_LIST_WORD_FIRST_LANE_CYCLES": str(
                args.candidate_list_word_first_lane_cycles
            ),
            "SPINE_SST_CANDIDATE_LIST_WORD_ADDITIONAL_LANE_CYCLES": str(
                args.candidate_list_word_additional_lane_cycles
            ),
            "SPINE_SST_CANDIDATE_PUBLICATION_BASE_CYCLES": str(
                args.candidate_publication_base_cycles
            ),
            "SPINE_SST_CANDIDATE_PUBLICATION_SOURCE_CYCLES": str(
                args.candidate_publication_source_cycles
            ),
            "SPINE_SST_CANDIDATE_PUBLICATION_GROUP_CYCLES": str(
                args.candidate_publication_group_cycles
            ),
            "SPINE_SST_CANDIDATE_PUBLICATION_NEW_BIT_CYCLES": str(
                args.candidate_publication_new_bit_cycles
            ),
            "SPINE_SST_CANDIDATE_PUBLICATION_PREFETCH_RESTART_CYCLES": str(
                args.candidate_publication_prefetch_restart_cycles
            ),
            "SPINE_SST_CANDIDATE_PUBLICATION_EMPTY_BASE_CYCLES": str(
                args.candidate_publication_empty_base_cycles
            ),
            "SPINE_SST_CANDIDATE_PUBLICATION_EMPTY_GROUP_CYCLES": str(
                args.candidate_publication_empty_group_cycles
            ),
            "SPINE_SST_CANDIDATE_PUBLICATION_FULL_WINDOW_REBATE_CYCLES": str(
                args.candidate_publication_full_window_rebate_cycles
            ),
            "SPINE_SST_CANDIDATE_PUBLICATION_NEXT_WINDOW_OVERLAP_CYCLES": str(
                args.candidate_publication_next_window_overlap_cycles
            ),
            "SPINE_SST_MAINTENANCE_SCAN_RESPONSE_CAPACITY": str(
                args.maintenance_scan_response_capacity
            ),
            "SPINE_SST_AXI_PROFILE": args.axi_profile,
            "SPINE_SST_MAINTENANCE_ARCHITECTURE": (
                args.maintenance_architecture
            ),
        }
    )
    command = [
        str(args.sst),
        sst_library["command_option"],
        str(ROOT / "sst" / "spine_vertical_slice.py"),
    ]
    sst_start = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    sst_host_wall_seconds = time.monotonic() - sst_start
    (args.out_dir / "sst.log").write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"SST Spine vertical slice failed with rc={completed.returncode}; "
            f"see {args.out_dir / 'sst.log'}"
        )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    dram = collect_dram_stats(args.out_dir)
    validators = {
        "amazon_l0": validate_result,
        "carry_hot": validate_carry_hot_result,
        "amazon_full_compute": validate_full_compute_result,
        "full_pagerank": validate_full_pagerank_result,
        "residual_pagerank": validate_residual_pagerank_result,
        "weighted_sssp": validate_multiround_sssp_result,
        "dynamic_sssp": validate_dynamic_sssp_result,
        "dynamic_sssp_delete": lambda result, dram, *, channels: (
            validate_nonmonotonic_sssp_result(
                result,
                dram,
                channels=channels,
                expected_values=[0, 5, 100, 101],
                expected_update_edges=1,
                expected_snapshot_edges=3,
                expected_dirty_sources=2,
                expected_rounds=3,
                expected_frontier_in=[1, 2, 1],
                expected_frontier_out=[2, 1, 0],
            )
        ),
        "dynamic_sssp_increase": lambda result, dram, *, channels: (
            validate_nonmonotonic_sssp_result(
                result,
                dram,
                channels=channels,
                expected_values=[0, 5, 55, 56],
                expected_update_edges=2,
                expected_snapshot_edges=4,
                expected_dirty_sources=3,
                expected_rounds=4,
                expected_frontier_in=[1, 2, 2, 1],
                expected_frontier_out=[2, 2, 1, 0],
            )
        ),
        "protocol_window": validate_protocol_window_result,
        "fallback_capacity": lambda result, dram, *, channels: (
            validate_fallback_result(
                result, dram, channels=channels, expected_reason=2
            )
        ),
        "fallback_payload": lambda result, dram, *, channels: (
            validate_fallback_result(
                result, dram, channels=channels, expected_reason=3
            )
        ),
    }
    if args.scenario == "candidate10_maintenance":
        problems = validate_candidate10_maintenance_result(
            result,
            dram,
            channels=len(binding.instantiated_channels),
            input_edges=workload_edges,
            core_mhz=core_mhz,
        )
    elif args.validation_mode == "generic":
        problems = validate_generic_result(
            result,
            dram,
            channels=len(binding.instantiated_channels),
            scenario=args.scenario,
            vertices=workload_vertices,
            input_edges=workload_edges,
            update_edges=update_edges,
            source=args.source,
            core_mhz=core_mhz,
            max_rounds=args.max_rounds,
            pagerank_iterations=args.pagerank_iterations,
            pagerank_damping=args.pagerank_damping,
            pagerank_epsilon=args.pagerank_epsilon,
            residual_max_iterations=args.residual_max_iterations,
            residual_contract=args.residual_contract,
        )
    else:
        validator = validators[args.scenario]
        problems = validator(
            result, dram, channels=len(binding.instantiated_channels)
        )
    if args.scenario in generic_scenarios:
        if result.get("architecture_correctness_mismatches") != 0:
            problems.append("architecture_correctness")
        if result.get("mathematical_correctness_mismatches") != 0:
            problems.append("mathematical_correctness")
        if not result.get("architecture_oracle"):
            problems.append("architecture_oracle")
        if not result.get("mathematical_oracle"):
            problems.append("mathematical_oracle")
        if abs(float(result.get("core_mhz", -1.0)) - core_mhz) > 1.0e-9:
            problems.append("core_mhz")
    if result.get("spine_axi_profile") != args.axi_profile:
        problems.append("axi_profile")
    if (
        result.get("spine_maintenance_architecture")
        != args.maintenance_architecture
    ):
        problems.append("maintenance_architecture")
    if (
        result.get("fallback_level_cache_reuse")
        is not args.fallback_level_cache_reuse
    ):
        problems.append("fallback_level_cache_reuse")
    if result.get("source_page_index_cache") is not args.source_page_index_cache:
        problems.append("source_page_index_cache")
    if args.scenario != "candidate10_maintenance" and (
        result.get("compute_memory_request_window")
        != args.compute_memory_request_window
    ):
        problems.append("compute_memory_request_window")
    if args.scenario in {"full_pagerank", "residual_pagerank"}:
        expected_pagerank_pipeline = {
            "pagerank_source_latency": args.pagerank_source_latency,
            "pagerank_source_ii": args.pagerank_source_ii,
            "pagerank_source_capacity": args.pagerank_source_capacity,
            "pagerank_edge_latency": args.pagerank_edge_latency,
            "pagerank_edge_ii": args.pagerank_edge_ii,
            "pagerank_edge_capacity": args.pagerank_edge_capacity,
            "pagerank_reduce_latency": args.pagerank_reduce_latency,
            "pagerank_reduce_ii": args.pagerank_reduce_ii,
            "pagerank_reduce_capacity": args.pagerank_reduce_capacity,
            "pagerank_apply_latency": args.pagerank_apply_latency,
            "pagerank_apply_ii": args.pagerank_apply_ii,
            "pagerank_apply_capacity": args.pagerank_apply_capacity,
        }
        for key, expected in expected_pagerank_pipeline.items():
            if result.get(key) != expected:
                problems.append(key)
    elif args.scenario != "candidate10_maintenance":
        if (
            result.get("compute_writeonly_request_window")
            != args.compute_writeonly_request_window
        ):
            problems.append("compute_writeonly_request_window")
        expected_onchip = {
            "compute_tiny_bram_read_latency": args.compute_tiny_bram_read_latency,
            "compute_vs_uram_read_latency": args.compute_vs_uram_read_latency,
            "compute_active_bram_read_latency": (
                args.compute_active_bram_read_latency
            ),
            "compute_onchip_pipeline_capacity": (
                args.compute_onchip_pipeline_capacity
            ),
            "compute_vs_bypass_depth": args.compute_vs_bypass_depth,
        }
        for key, expected in expected_onchip.items():
            if result.get(key) != expected:
                problems.append(key)
    expected_timing = {
        "maintenance_count_scan_ii": args.maintenance_count_scan_ii,
        "maintenance_count_scan_tail_cycles": args.maintenance_count_scan_tail_cycles,
        "maintenance_l0_write_scan_ii": args.maintenance_l0_write_scan_ii,
        "maintenance_l0_write_scan_tail_cycles": (
            args.maintenance_l0_write_scan_tail_cycles
        ),
        "candidate_l0_precount_ii": args.candidate_l0_precount_ii,
        "candidate_l0_precount_tail_cycles": (
            args.candidate_l0_precount_tail_cycles
        ),
        "candidate_l0_write_scan_ii": args.candidate_l0_write_scan_ii,
        "candidate_l0_write_scan_tail_cycles": (
            args.candidate_l0_write_scan_tail_cycles
        ),
        "candidate_l0_writer_rtl_schedule": (
            args.candidate_l0_writer_rtl_schedule
        ),
        "candidate_l0_writer_base_residual_cycles": (
            args.candidate_l0_writer_base_residual_cycles
        ),
        "candidate_l0_writer_single_record_cycles": (
            args.candidate_l0_writer_single_record_cycles
        ),
        "candidate_l0_writer_late_source_cycles": (
            args.candidate_l0_writer_late_source_cycles
        ),
        "candidate_l0_writer_packer_cycles": (
            args.candidate_l0_writer_packer_cycles
        ),
        "candidate_l0_writer_page_tail_cycles": (
            args.candidate_l0_writer_page_tail_cycles
        ),
        "candidate_list_word_first_lane_cycles": (
            args.candidate_list_word_first_lane_cycles
        ),
        "candidate_list_word_additional_lane_cycles": (
            args.candidate_list_word_additional_lane_cycles
        ),
        "candidate_publication_base_cycles": args.candidate_publication_base_cycles,
        "candidate_publication_source_cycles": (
            args.candidate_publication_source_cycles
        ),
        "candidate_publication_group_cycles": args.candidate_publication_group_cycles,
        "candidate_publication_new_bit_cycles": (
            args.candidate_publication_new_bit_cycles
        ),
        "candidate_publication_prefetch_restart_cycles": (
            args.candidate_publication_prefetch_restart_cycles
        ),
        "candidate_publication_empty_base_cycles": (
            args.candidate_publication_empty_base_cycles
        ),
        "candidate_publication_empty_group_cycles": (
            args.candidate_publication_empty_group_cycles
        ),
        "candidate_publication_full_window_rebate_cycles": (
            args.candidate_publication_full_window_rebate_cycles
        ),
        "candidate_publication_next_window_overlap_cycles": (
            args.candidate_publication_next_window_overlap_cycles
        ),
        "maintenance_scan_response_capacity": (
            args.maintenance_scan_response_capacity
        ),
    }
    if not maintenance_timing_profile_matches(result, expected_timing):
        problems.append("maintenance_scan_timing_profile")
    if problems:
        raise RuntimeError(f"SST Spine checks failed: {', '.join(problems)}")
    summary_result = dict(result)
    final_values = summary_result.get("final_values")
    if isinstance(final_values, list) and len(final_values) > 4_096:
        encoded_values = json.dumps(final_values, separators=(",", ":")).encode(
            "ascii"
        )
        summary_result["final_values_count"] = len(final_values)
        summary_result["final_values_sha256"] = hashlib.sha256(
            encoded_values
        ).hexdigest()
        sample_indices = (0, 1, 65_536, len(final_values) - 1)
        summary_result["final_value_samples"] = {
            str(index): final_values[index]
            for index in sample_indices
            if index < len(final_values)
        }
        del summary_result["final_values"]
    summary = {
        **summary_result,
        **dram,
        "architecture_profile_id": profile["profile_id"],
        "architecture_profile_path": str(profile_path),
        "architecture_profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
        "source_revision": profile["source"]["revision"],
        "architecture_profile_evidence_tier": profile["evidence_tier"],
        "simulation_evidence_tier": "structural_execution_driven",
        "range_task_active_gate": args.range_task_active_gate,
        "range_task_capacity": args.range_task_capacity,
        "range_task_payload_budget": args.range_task_payload_budget,
        "sst_memory_binding": binding.as_manifest(),
        "sst_library_binding": sst_library,
        "sst_plugin_sha256": sst_library["plugin_sha256"],
        "workload_sha256": sha256_file(args.workload),
        "update_workload_sha256": (
            sha256_file(args.update_workload)
            if args.update_workload is not None
            else None
        ),
        "dram_energy_claim": binding.energy_claim,
        "sst_host_wall_seconds": sst_host_wall_seconds,
        "status": "PASS",
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"PASS spine_vertical: cycles={result['cycles']} "
        f"backend_requests={result['backend_requests']} "
        f"DRAM={int(dram['dram_reads']) + int(dram['dram_writes'])} "
        f"ACT={dram['dram_activates']} row_hits="
        f"{int(dram['dram_read_row_hits']) + int(dram['dram_write_row_hits'])}"
    )
    print(f"evidence: {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
