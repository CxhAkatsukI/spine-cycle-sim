from __future__ import annotations

import unittest

from scripts.run_sst_spine_vertical import validate_carry_hot_result, validate_result


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
            "reader_tiles": 5,
            "reader_edges": 10,
            "reader_graph_bytes": 224,
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
            "reader_graph_bytes": 224,
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
            "reader_graph_bytes": 224,
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
            "maintenance_carry_payload_reads": 1,
            "maintenance_carry_merge_inputs": 2,
            "maintenance_carry_outputs": 2,
            "reader_tiles": 1,
            "reader_edges": 3,
            "reader_graph_bytes": 176,
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


if __name__ == "__main__":
    unittest.main()
