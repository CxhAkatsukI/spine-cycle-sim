#!/usr/bin/env python3
"""Run and validate the real Spine vertical slice on SST-HBM."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_WORKLOAD = ROOT / "tests" / "data" / "amazon_top1_exact.slice"
DEFAULT_CARRY_WORKLOAD = ROOT / "tests" / "data" / "carry_hot_batch.slice"
DEFAULT_CARRY_PRELOAD = ROOT / "tests" / "data" / "carry_hot_preload.slice"
DEFAULT_FULL_WORKLOAD = (
    ROOT / "tests" / "data" / "amazon_densewin8192_active7893_exact.slice"
)
DEFAULT_SSSP_WORKLOAD = ROOT / "tests" / "data" / "weighted_chain_shortcut.slice"
DEFAULT_PROTOCOL_WORKLOAD = (
    ROOT / "tests" / "data" / "source_protocol_window_17.slice"
)
DEFAULT_FALLBACK_WORKLOAD = (
    ROOT / "tests" / "data" / "fallback_three_tiles.slice"
)
PROFILE_PATH = ROOT / "configs" / "architectures" / "spine_shared_engine_9c08763.json"


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
    parser.add_argument(
        "--scenario",
        choices=(
            "amazon_l0",
            "carry_hot",
            "amazon_full_compute",
            "weighted_sssp",
            "protocol_window",
            "fallback_capacity",
            "fallback_payload",
        ),
        default="amazon_l0",
    )
    parser.add_argument("--preload", type=Path)
    parser.add_argument("--hot-vertices", default="")
    parser.add_argument("--source", type=int)
    parser.add_argument("--channels", type=int, default=32)
    parser.add_argument("--device-dirty-source-limit", type=int, default=4_096)
    parser.add_argument("--range-task-active-gate", type=int, default=16_384)
    parser.add_argument("--range-task-capacity", type=int, default=65_536)
    parser.add_argument(
        "--range-task-payload-budget", type=int, default=1_048_576
    )
    parser.add_argument("--fallback-replay-threshold", type=int, default=65_536)
    parser.add_argument(
        "--memory-request-window",
        type=int,
        default=1,
        help=(
            "coarse logical-request overlap; values above one are an "
            "architecture what-if, not the source-faithful HLS default"
        ),
    )
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
    parser.add_argument(
        "--maintenance-scan-response-capacity", type=int, default=32
    )
    parser.add_argument(
        "--axi-profile",
        choices=("hls_split_9c08763", "legacy_uniform64"),
        default="hls_split_9c08763",
    )
    parser.add_argument("--no-build", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
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
        or args.maintenance_count_scan_tail_cycles < 0
        or args.maintenance_l0_write_scan_tail_cycles < 0
        or args.maintenance_scan_response_capacity <= 0
    ):
        raise SystemExit("maintenance scan IIs must be positive and tails non-negative")
    if args.preload is not None and not args.preload.is_file():
        raise SystemExit(f"preload workload is missing: {args.preload}")
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst"], cwd=ROOT, check=True)
    library = args.lib_dir / "libspine_cycle.so"
    if not library.is_file():
        raise SystemExit(f"missing SST element library: {library}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.out_dir / "result.json"
    env = os.environ.copy()
    env.update(
        {
            "SPINE_SST_CHANNELS": str(args.channels),
            "SPINE_SST_MODE": {
                "amazon_full_compute": "spine_compute",
                "weighted_sssp": "spine_sssp",
                "fallback_capacity": "spine_sssp",
                "fallback_payload": "spine_sssp",
            }.get(args.scenario, "spine_vertical"),
            "SPINE_SST_WORKLOAD": str(args.workload.resolve()),
            "SPINE_SST_SOURCE": str(args.source),
            "SPINE_SST_PRELOAD": ""
            if args.preload is None
            else str(args.preload.resolve()),
            "SPINE_SST_HOT_VERTICES": args.hot_vertices,
            "SPINE_SST_OUTPUT": str(result_path),
            "SPINE_SST_DRAM_OUTPUT": str(args.out_dir / "dram"),
            "SPINE_SST_MAX_CYCLES": "5000000"
            if args.scenario == "amazon_full_compute"
            else "1000000",
            "SPINE_SST_MAX_ROUNDS": "256",
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
            "SPINE_SST_MEMORY_REQUEST_WINDOW": str(args.memory_request_window),
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
            "SPINE_SST_MAINTENANCE_SCAN_RESPONSE_CAPACITY": str(
                args.maintenance_scan_response_capacity
            ),
            "SPINE_SST_AXI_PROFILE": args.axi_profile,
        }
    )
    command = [
        str(args.sst),
        f"--add-lib-path={args.lib_dir}",
        str(ROOT / "sst" / "spine_vertical_slice.py"),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
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
        "weighted_sssp": validate_multiround_sssp_result,
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
    validator = validators[args.scenario]
    problems = validator(result, dram, channels=args.channels)
    if result.get("spine_axi_profile") != args.axi_profile:
        problems.append("axi_profile")
    expected_timing = {
        "maintenance_count_scan_ii": args.maintenance_count_scan_ii,
        "maintenance_count_scan_tail_cycles": args.maintenance_count_scan_tail_cycles,
        "maintenance_l0_write_scan_ii": args.maintenance_l0_write_scan_ii,
        "maintenance_l0_write_scan_tail_cycles": (
            args.maintenance_l0_write_scan_tail_cycles
        ),
        "maintenance_scan_response_capacity": (
            args.maintenance_scan_response_capacity
        ),
    }
    if any(result.get(field) != value for field, value in expected_timing.items()):
        problems.append("maintenance_scan_timing_profile")
    if problems:
        raise RuntimeError(f"SST Spine checks failed: {', '.join(problems)}")
    profile_bytes = PROFILE_PATH.read_bytes()
    profile = json.loads(profile_bytes)
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
        "architecture_profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
        "source_revision": profile["source"]["revision"],
        "architecture_profile_evidence_tier": profile["evidence_tier"],
        "simulation_evidence_tier": "structural_execution_driven",
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
