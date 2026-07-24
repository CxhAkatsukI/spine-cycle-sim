from __future__ import annotations

import unittest

from scripts.run_sst_spine_vertical import (
    validate_carry_hot_result,
    validate_full_compute_result,
    validate_multiround_sssp_result,
    validate_result,
)


class SstSpineVerticalValidationTests(unittest.TestCase):
    def test_matching_architecture_and_dram_counts_pass(self) -> None:
        result = {
            "success": True,
            "mode": "spine_vertical",
            "correctness_mismatches": 0,
            "frontier_mismatches": 0,
            "next_active": 10,
            "maintenance_scan_passes": 19,
            "maintenance_edge_visits": 190,
            "maintenance_sorted_bytes": 3_040,
            "maintenance_sorted_payload_read_bytes": 3_040,
            "reader_tiles": 5,
            "reader_edges": 10,
            "reader_graph_bytes": 184,
            "maintenance_graph_index_payload_write_bytes": 64,
            "maintenance_graph_payload_write_bytes": 80,
            "reader_graph_index_payload_bytes": 24,
            "reader_graph_payload_bytes": 160,
            "reader_construction_payload_bytes": 80,
            "reader_replay_payload_bytes": 80,
            "reader_graph_index_bitmap_misses": 0,
            "reader_range_path": 1,
            "reader_range_error": 0,
            "reader_range_fallback_reason": 0,
            "reader_range_tasks": 5,
            "reader_range_level_checks": 176,
            "reader_range_construction_payloads": 10,
            "reader_range_replay_payloads": 10,
            "reader_range_clear_cycles": 256,
            "reader_range_prefix_cycles": 256,
            "reader_range_scatter_cycles": 5,
            "reader_range_verify_cycles": 256,
            "reader_metadata_bytes": 2_952,
            "reader_occupied_levels": 1,
            "compute_fast_tiles": 5,
            "compute_full_tiles": 0,
            "compute_processed_edges": 10,
            "edge_axis_transfers": 22,
            "edge_axis_max_occupancy": 15,
            "backend_requests": 100,
        }
        dram = {"dram_reads": 60, "dram_writes": 40, "dram_channels": 32}
        self.assertEqual(validate_result(result, dram, channels=32), [])

    def test_dram_request_drop_is_rejected(self) -> None:
        result = {
            "success": True,
            "mode": "spine_vertical",
            "correctness_mismatches": 0,
            "frontier_mismatches": 0,
            "next_active": 10,
            "maintenance_scan_passes": 19,
            "maintenance_edge_visits": 190,
            "maintenance_sorted_bytes": 3_040,
            "reader_tiles": 5,
            "reader_edges": 10,
            "reader_graph_bytes": 112,
            "reader_metadata_bytes": 2_952,
            "reader_occupied_levels": 1,
            "compute_fast_tiles": 5,
            "compute_full_tiles": 0,
            "compute_processed_edges": 10,
            "edge_axis_transfers": 22,
            "edge_axis_max_occupancy": 15,
            "backend_requests": 100,
        }
        dram = {"dram_reads": 59, "dram_writes": 40, "dram_channels": 32}
        self.assertIn(
            "dram_matches_backend", validate_result(result, dram, channels=32)
        )

    def test_frontier_mismatch_is_rejected(self) -> None:
        result = {
            "success": True,
            "mode": "spine_vertical",
            "correctness_mismatches": 0,
            "frontier_mismatches": 1,
            "next_active": 10,
            "maintenance_scan_passes": 19,
            "maintenance_edge_visits": 190,
            "maintenance_sorted_bytes": 3_040,
            "reader_tiles": 5,
            "reader_edges": 10,
            "reader_graph_bytes": 112,
            "reader_metadata_bytes": 2_952,
            "reader_occupied_levels": 1,
            "compute_fast_tiles": 5,
            "compute_full_tiles": 0,
            "compute_processed_edges": 10,
            "edge_axis_transfers": 22,
            "edge_axis_max_occupancy": 15,
            "backend_requests": 100,
        }
        dram = {"dram_reads": 60, "dram_writes": 40, "dram_channels": 32}
        self.assertIn(
            "frontier_correctness", validate_result(result, dram, channels=32)
        )

    def test_carry_hot_structure_and_memory_closure_pass(self) -> None:
        result = {
            "success": True,
            "mode": "spine_vertical",
            "correctness_mismatches": 0,
            "frontier_mismatches": 0,
            "next_active": 3,
            "input_edges": 2,
            "preload_edges": 1,
            "maintenance_target_level": 1,
            "maintenance_hot_target_level": 0,
            "maintenance_cold_input_edges": 1,
            "maintenance_hot_input_edges": 1,
            "maintenance_scan_passes": 35,
            "maintenance_edge_visits": 70,
            "maintenance_sorted_bytes": 1_120,
            "maintenance_sorted_payload_read_bytes": 1_120,
            "maintenance_carry_payload_reads": 1,
            "maintenance_carry_payload_read_bytes": 8,
            "maintenance_carry_merge_inputs": 2,
            "maintenance_carry_outputs": 2,
            "reader_tiles": 1,
            "reader_edges": 3,
            "reader_graph_bytes": 96,
            "maintenance_graph_index_payload_write_bytes": 128,
            "maintenance_graph_payload_write_bytes": 24,
            "reader_graph_index_payload_bytes": 48,
            "reader_graph_payload_bytes": 48,
            "reader_construction_payload_bytes": 24,
            "reader_replay_payload_bytes": 24,
            "reader_graph_index_bitmap_misses": 0,
            "reader_range_path": 1,
            "reader_range_error": 0,
            "reader_range_fallback_reason": 0,
            "reader_range_tasks": 2,
            "reader_range_level_checks": 352,
            "reader_range_construction_payloads": 3,
            "reader_range_replay_payloads": 3,
            "reader_metadata_bytes": 3_024,
            "reader_occupied_levels": 2,
            "reader_cold_edges": 2,
            "reader_hot_edges": 1,
            "compute_fast_tiles": 1,
            "compute_full_tiles": 0,
            "compute_processed_edges": 3,
            "edge_axis_max_occupancy": 5,
            "backend_requests": 100,
        }
        dram = {"dram_reads": 60, "dram_writes": 40, "dram_channels": 32}
        self.assertEqual(validate_carry_hot_result(result, dram, channels=32), [])

    def test_real_full_tile_compute_structure_passes(self) -> None:
        result = {
            "success": True,
            "mode": "spine_compute",
            "correctness_mismatches": 0,
            "frontier_mismatches": 0,
            "expected_frontier": 40_000,
            "next_active": 40_000,
            "input_edges": 64_658,
            "compute_fast_tiles": 11,
            "compute_full_tiles": 1,
            "compute_processed_edges": 64_658,
            "compute_gathered_words": 14_676,
            "compute_swept_words": 131_072,
            "compute_full_buffer_replay_edges": 4096,
            "compute_full_overflow_edges": 1,
            "compute_full_stream_edges": 45_885,
            "compute_vertex_read_bytes": 320_848,
            "compute_vertex_payload_read_bytes": 320_848,
            "compute_vertex_write_bytes": 303_192,
            "compute_vertex_payload_write_bytes": 303_192,
            "edge_axis_transfers": 64_683,
            "edge_axis_max_occupancy": 32,
            "edge_axis_push_stalls": 10,
            "backend_requests": 100,
        }
        dram = {"dram_reads": 60, "dram_writes": 40, "dram_channels": 32}
        self.assertEqual(validate_full_compute_result(result, dram, channels=32), [])

    def test_real_full_tile_without_axis_backpressure_is_rejected(self) -> None:
        result = {
            "success": True,
            "mode": "spine_compute",
            "correctness_mismatches": 0,
            "frontier_mismatches": 0,
            "expected_frontier": 40_000,
            "next_active": 40_000,
            "input_edges": 64_658,
            "compute_fast_tiles": 11,
            "compute_full_tiles": 1,
            "compute_processed_edges": 64_658,
            "compute_gathered_words": 14_676,
            "compute_swept_words": 131_072,
            "compute_full_buffer_replay_edges": 4096,
            "compute_full_overflow_edges": 1,
            "compute_full_stream_edges": 45_885,
            "edge_axis_transfers": 64_683,
            "edge_axis_max_occupancy": 32,
            "edge_axis_push_stalls": 0,
            "backend_requests": 100,
        }
        dram = {"dram_reads": 60, "dram_writes": 40, "dram_channels": 32}
        self.assertIn(
            "axis_backpressure",
            validate_full_compute_result(result, dram, channels=32),
        )

    def test_multiround_weighted_sssp_structure_passes(self) -> None:
        result = {
            "success": True,
            "mode": "spine_sssp",
            "converged": True,
            "correctness_mismatches": 0,
            "frontier_mismatches": 0,
            "input_edges": 8,
            "rounds": 6,
            "final_values": [0, 3, 2, 7, 8, 10],
            "frontier_in_sizes": [1, 3, 2, 2, 2, 1],
            "frontier_out_sizes": [3, 2, 2, 2, 1, 0],
            "processed_edges_per_round": [3, 3, 2, 2, 1, 0],
            "maintenance_scan_passes": 19,
            "maintenance_edge_visits": 152,
            "maintenance_sorted_bytes": 2_432,
            "maintenance_sorted_payload_read_bytes": 2_432,
            "round_cycles": [10, 11, 12, 13, 14, 15],
            "edge_axis_max_occupancy_per_round": [5, 6, 5, 5, 4, 2],
            "edge_axis_push_stalls_per_round": [0, 1, 0, 0, 0, 0],
            "fast_tiles_per_round": [1, 1, 1, 1, 1, 0],
            "full_tiles_per_round": [0, 0, 0, 0, 0, 0],
            "reader_metadata_bytes_per_round": [100] * 6,
            "maintenance_graph_index_payload_write_bytes": 88,
            "maintenance_graph_payload_write_bytes": 64,
            "reader_graph_index_payload_bytes_per_round": [24, 64, 64, 56, 32, 8],
            "reader_graph_payload_bytes_per_round": [48, 48, 32, 32, 16, 0],
            "reader_construction_payload_bytes_per_round": [24, 24, 16, 16, 8, 0],
            "reader_replay_payload_bytes_per_round": [24, 24, 16, 16, 8, 0],
            "reader_graph_index_bitmap_misses_per_round": [0, 1, 0, 0, 1, 1],
            "reader_range_tasks_per_round": [1, 2, 2, 2, 1, 0],
            "reader_range_row_lookups_per_round": [1, 3, 2, 2, 2, 1],
            "reader_range_level_checks_per_round": [176, 528, 352, 352, 352, 176],
            "backend_requests": 100,
        }
        dram = {"dram_reads": 60, "dram_writes": 40, "dram_channels": 32}
        self.assertEqual(
            validate_multiround_sssp_result(result, dram, channels=32), []
        )


if __name__ == "__main__":
    unittest.main()
