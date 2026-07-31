from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.run_sst_spine_vertical import (
    load_slice_shape,
    maintenance_timing_profile_matches,
    sha256_file,
    validate_carry_hot_result,
    validate_dynamic_sssp_result,
    validate_fallback_result,
    validate_full_rebuild_capacity,
    validate_full_compute_result,
    validate_full_pagerank_result,
    validate_generic_result,
    validate_multiround_sssp_result,
    validate_nonmonotonic_sssp_result,
    validate_protocol_window_result,
    validate_residual_pagerank_result,
    validate_result,
)


ROOT = Path(__file__).resolve().parents[1]


class SstSpineVerticalValidationTests(unittest.TestCase):
    def test_large_file_helpers_stream_slice_shape_and_sha(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "graph.slice"
            path.write_text(
                "# spine_real_slice_version=1\n"
                "# vertices=9\n"
                "0 1 2 1\n"
                "7 8 3 -1\n",
                encoding="ascii",
            )
            self.assertEqual(load_slice_shape(path), (9, 2))
            self.assertEqual(
                sha256_file(path),
                "b41873890369e7f277fe83edbbe1a0e321044dec6be9abf5eb03a583a5247111",
            )

    def test_nonmonotonic_full_rebuild_capacity_fails_before_bootstrap(self) -> None:
        validate_full_rebuild_capacity(64_000, 8)
        with self.assertRaisesRegex(ValueError, "MAX_SORT_EDGES=131072"):
            validate_full_rebuild_capacity(390_847, 8)

    def test_generic_full_pagerank_accepts_dual_oracle_result(self) -> None:
        result = {
            "success": True,
            "mode": "spine_pagerank",
            "core_mhz": 150.0,
            "vertices": 4,
            "input_edges": 4,
            "architecture_oracle": "iterative_float32",
            "mathematical_oracle": "iterative_float64",
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "correctness_mismatches": 0,
            "pagerank_iterations": 3,
            "pagerank_completed_iterations": 3,
            "pagerank_damping": 0.85,
            "iteration_cycles": [100, 90, 80],
            "ranks": [0.25, 0.25, 0.25, 0.25],
            "max_abs_error": 1.0e-7,
            "mathematical_max_abs_error": 1.0e-7,
            "reader_protocol_status": 0,
            "backend_requests": 12,
        }
        dram = {"dram_reads": 10, "dram_writes": 2, "dram_channels": 32}
        self.assertEqual(
            validate_generic_result(
                result,
                dram,
                channels=32,
                scenario="full_pagerank",
                vertices=4,
                input_edges=4,
                update_edges=0,
                source=0,
                core_mhz=150.0,
                max_rounds=256,
                pagerank_iterations=3,
                pagerank_damping=0.85,
                pagerank_epsilon=1.0e-6,
                residual_max_iterations=256,
            ),
            [],
        )

    def test_generic_dynamic_pagerank_requires_final_snapshot_contract(self) -> None:
        result = {
            "success": True,
            "mode": "spine_pagerank",
            "core_mhz": 141.0,
            "vertices": 4,
            "input_edges": 4,
            "initial_edges": 4,
            "update_edges": 2,
            "materialized_snapshot_edges": 4,
            "maintenance_persisted_edges": 4,
            "reader_edges": 4,
            "maintenance_backend_requests": 5,
            "compute_backend_requests": 7,
            "dynamic_update": True,
            "pipeline_order": (
                "zero_time_resident_level_preload_then_update_maintenance_then_compute"
            ),
            "architecture_oracle": "iterative_float32",
            "mathematical_oracle": "iterative_float64",
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "correctness_mismatches": 0,
            "pagerank_iterations": 3,
            "pagerank_completed_iterations": 3,
            "pagerank_damping": 0.85,
            "iteration_cycles": [100, 90, 80],
            "ranks": [0.25, 0.25, 0.25, 0.25],
            "max_abs_error": 1.0e-7,
            "mathematical_max_abs_error": 1.0e-7,
            "reader_protocol_status": 0,
            "backend_requests": 12,
        }
        dram = {"dram_reads": 10, "dram_writes": 2, "dram_channels": 32}
        arguments = dict(
            channels=32,
            scenario="full_pagerank",
            vertices=4,
            input_edges=4,
            update_edges=2,
            source=0,
            core_mhz=141.0,
            max_rounds=256,
            pagerank_iterations=3,
            pagerank_damping=0.85,
            pagerank_epsilon=1.0e-6,
            residual_max_iterations=256,
        )
        self.assertEqual(validate_generic_result(result, dram, **arguments), [])
        result["maintenance_persisted_edges"] = 5
        self.assertIn(
            "materialized_snapshot",
            validate_generic_result(result, dram, **arguments),
        )
        result["maintenance_persisted_edges"] = 0
        self.assertNotIn(
            "materialized_snapshot",
            validate_generic_result(result, dram, **arguments),
        )
        result["maintenance_persisted_edges"] = 4
        result["reader_edges"] = 3
        self.assertIn(
            "materialized_reader",
            validate_generic_result(result, dram, **arguments),
        )

    def test_generic_dynamic_residual_may_scan_only_active_edges(self) -> None:
        result = {
            "success": True,
            "mode": "spine_residual_pagerank",
            "core_mhz": 141.0,
            "input_edges": 4,
            "initial_edges": 4,
            "update_edges": 2,
            "materialized_snapshot_edges": 4,
            "maintenance_persisted_edges": 4,
            "reader_edges": 0,
            "maintenance_backend_requests": 5,
            "compute_backend_requests": 7,
            "backend_requests": 12,
            "dynamic_update": True,
            "pipeline_order": (
                "zero_time_resident_level_preload_then_update_maintenance_then_compute"
            ),
            "architecture_oracle": "residual_float32",
            "mathematical_oracle": "residual_float64",
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "correctness_mismatches": 0,
        }
        dram = {"dram_reads": 8, "dram_writes": 4, "dram_channels": 32}
        problems = validate_generic_result(
            result,
            dram,
            channels=32,
            scenario="residual_pagerank",
            vertices=4,
            input_edges=4,
            update_edges=2,
            source=0,
            core_mhz=141.0,
            max_rounds=256,
            pagerank_iterations=3,
            pagerank_damping=0.85,
            pagerank_epsilon=1.0e-6,
            residual_max_iterations=256,
        )
        self.assertNotIn("materialized_reader", problems)

    def test_delta_hls_residual_uses_linf_and_requires_sink_free_snapshots(self) -> None:
        result = {
            "success": True,
            "mode": "spine_residual_pagerank",
            "core_mhz": 141.0,
            "vertices": 4,
            "input_edges": 4,
            "initial_edges": 4,
            "update_edges": 2,
            "materialized_snapshot_edges": 6,
            "maintenance_persisted_edges": 2,
            "maintenance_backend_requests": 5,
            "compute_backend_requests": 7,
            "backend_requests": 12,
            "dynamic_update": True,
            "pipeline_order": (
                "zero_time_resident_old_rank_then_update_maintenance_then_device_correction_seed_then_compute"
            ),
            "residual_correction_device_timed": True,
            "residual_correction_request_ledger_closed": True,
            "architecture_oracle": "deltahls_residual_float32",
            "mathematical_oracle": "full_pagerank_float64",
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "correctness_mismatches": 0,
            "converged": True,
            "final_active": 0,
            "iterations": 2,
            "pagerank_damping": 0.85,
            "pagerank_epsilon": 1.0e-4,
            "residual_contract": "deltahls_sink_free_linf_warm",
            "old_sink_vertices": 0,
            "new_sink_vertices": 0,
            "ranks": [0.25] * 4,
            "residuals": [9.0e-5] * 4,
            "residual_l1": 3.6e-4,
            "residual_linf": 9.0e-5,
            "residual_bound_passed": True,
            "frontier_in_sizes": [2, 1],
            "frontier_out_sizes": [1, 0],
            "frontier_match": True,
            "memory_ledger_match": True,
            "max_abs_error": 1.0e-7,
            "mathematical_max_abs_error": 1.0e-5,
            "mathematical_error_tolerance": 5.0e-4,
            "reader_protocol_status": 0,
        }
        dram = {"dram_reads": 8, "dram_writes": 4, "dram_channels": 32}
        arguments = dict(
            channels=32,
            scenario="residual_pagerank",
            vertices=4,
            input_edges=4,
            update_edges=2,
            source=0,
            core_mhz=141.0,
            max_rounds=256,
            pagerank_iterations=3,
            pagerank_damping=0.85,
            pagerank_epsilon=1.0e-4,
            residual_max_iterations=256,
            residual_contract="deltahls_sink_free_linf_warm",
        )
        self.assertEqual(validate_generic_result(result, dram, **arguments), [])
        result["residual_correction_device_timed"] = False
        self.assertIn(
            "device_residual_correction",
            validate_generic_result(result, dram, **arguments),
        )
        result["residual_correction_device_timed"] = True
        result["new_sink_vertices"] = 1
        self.assertIn("sink_free", validate_generic_result(result, dram, **arguments))

    def test_dynamic_sssp_closes_cold_update_and_memory_ledgers(self) -> None:
        result = {
            "success": True,
            "mode": "spine_sssp",
            "dynamic_update": True,
            "dynamic_update_path": "incremental_relax",
            "materialized_snapshot_edges": 5,
            "cold_correctness_mismatches": 0,
            "cold_frontier_mismatches": 0,
            "cold_final_values": [0, 5, 10, 11],
            "correctness_mismatches": 0,
            "full_recompute_correctness_mismatches": 0,
            "frontier_mismatches": 0,
            "final_values": [0, 5, 2, 3],
            "input_edges": 4,
            "update_edges": 1,
            "cold_rounds": 4,
            "cold_maintenance_target_level": 0,
            "cold_dirty_generation_after_ack": 2,
            "cold_cycles": 25_000,
            "cold_maintenance_cycles": 2_000,
            "cold_round_cycles": [8_000, 6_000, 6_000, 5_000],
            "rounds": 3,
            "maintenance_target_level": 1,
            "maintenance_persisted_edges": 4,
            "maintenance_dirty_generation": 3,
            "dirty_ack_captured_generation": 3,
            "dirty_ack_result_generation": 4,
            "update_cycles": 19_000,
            "frontier_in_sizes": [1, 1, 1],
            "frontier_out_sizes": [1, 1, 0],
            "processed_edges_per_round": [2, 1, 0],
            "reader_dirty_counts_per_round": [1, 0, 0],
            "reader_dirty_generations_per_round": [3, 4, 4],
            "maintenance_scan_passes": 19,
            "maintenance_edge_visits": 19,
            "maintenance_sorted_bytes": 320,
            "maintenance_sorted_payload_read_bytes": 320,
            "maintenance_carry_new_batch_reads": 1,
            "maintenance_carry_new_batch_read_bytes": 16,
            "maintenance_dirty_count": 1,
            "maintenance_dirty_unique_sources": 1,
            "cold_backend_requests": 2_982,
            "update_backend_requests": 2_509,
            "backend_requests": 5_491,
        }
        dram = {"dram_reads": 4_000, "dram_writes": 1_491, "dram_channels": 32}
        self.assertEqual(
            validate_dynamic_sssp_result(result, dram, channels=32), []
        )

        result["frontier_mismatches"] = 1
        self.assertIn(
            "update_correctness",
            validate_dynamic_sssp_result(result, dram, channels=32),
        )

    def test_frozen_nonmonotonic_sssp_evidence_passes(self) -> None:
        cases = (
            (
                "sst_spine_dynamic_delete_20260725_summary.json",
                {
                    "expected_values": [0, 5, 100, 101],
                    "expected_update_edges": 1,
                    "expected_snapshot_edges": 3,
                    "expected_dirty_sources": 2,
                    "expected_rounds": 3,
                    "expected_frontier_in": [1, 2, 1],
                    "expected_frontier_out": [2, 1, 0],
                },
            ),
            (
                "sst_spine_dynamic_increase_20260725_summary.json",
                {
                    "expected_values": [0, 5, 55, 56],
                    "expected_update_edges": 2,
                    "expected_snapshot_edges": 4,
                    "expected_dirty_sources": 3,
                    "expected_rounds": 4,
                    "expected_frontier_in": [1, 2, 2, 1],
                    "expected_frontier_out": [2, 2, 1, 0],
                },
            ),
        )
        for filename, expected in cases:
            with self.subTest(filename=filename):
                summary = json.loads(
                    (ROOT / "docs" / "evidence" / filename).read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    validate_nonmonotonic_sssp_result(
                        summary, summary, channels=32, **expected
                    ),
                    [],
                )

    def test_residual_pagerank_result_checks_frontier_and_memory_ledger(
        self,
    ) -> None:
        result = {
            "success": True,
            "mode": "spine_residual_pagerank",
            "timing_evidence": "provisional_algorithm_pipeline",
            "vertices": 4,
            "input_edges": 4,
            "converged": True,
            "final_active": 0,
            "iterations": 49,
            "frontier_in_sizes": [4, 3] + [2] * 46 + [1],
            "frontier_out_sizes": [3] + [2] * 46 + [1, 0],
            "compute_requests_per_iteration": [31, 25] + [20] * 45 + [19, 13],
            "correctness_mismatches": 0,
            "frontier_match": True,
            "memory_ledger_match": True,
            "max_abs_error": 1.0e-7,
            "pagerank_epsilon": 1.0e-5,
            "residual_l1": 5.0e-6,
            "maintenance_persisted_edges": 4,
            "maintenance_cycles": 50,
            "backend_requests": 100,
        }
        dram = {"dram_reads": 80, "dram_writes": 20, "dram_channels": 32}
        self.assertEqual(
            validate_residual_pagerank_result(result, dram, channels=32), []
        )

    def test_residual_pagerank_result_rejects_hidden_full_frontier(self) -> None:
        result = {
            "success": True,
            "mode": "spine_residual_pagerank",
            "timing_evidence": "provisional_algorithm_pipeline",
            "vertices": 4,
            "input_edges": 4,
            "converged": True,
            "final_active": 0,
            "iterations": 49,
            "frontier_in_sizes": [4] * 49,
            "frontier_out_sizes": [4] * 48 + [0],
            "compute_requests_per_iteration": [28] * 49,
            "correctness_mismatches": 0,
            "frontier_match": True,
            "memory_ledger_match": True,
            "max_abs_error": 0.0,
            "pagerank_epsilon": 1.0e-5,
            "residual_l1": 0.0,
            "maintenance_persisted_edges": 4,
            "maintenance_cycles": 50,
            "backend_requests": 100,
        }
        dram = {"dram_reads": 80, "dram_writes": 20, "dram_channels": 32}
        self.assertIn(
            "known_default_frontier",
            validate_residual_pagerank_result(result, dram, channels=32),
        )

    def test_full_pagerank_result_closes_algorithm_and_dram_ledgers(self) -> None:
        result = {
            "success": True,
            "mode": "spine_pagerank",
            "timing_evidence": "provisional_algorithm_pipeline",
            "vertices": 4,
            "input_edges": 4,
            "pagerank_iterations": 2,
            "pagerank_completed_iterations": 2,
            "iteration_cycles": [100, 80],
            "correctness_mismatches": 0,
            "max_abs_error": 1.0e-7,
            "ranks": [0.17, 0.21, 0.45, 0.17],
            "reference_ranks": [0.17, 0.21, 0.45, 0.17],
            "rank_sum": 1.0,
            "maintenance_persisted_edges": 4,
            "maintenance_cycles": 50,
            "reader_edges": 4,
            "reader_graph_payload_bytes": 64,
            "reader_source_requests": 4,
            "reader_source_responses": 4,
            "reader_source_windows": 1,
            "reader_protocol_status": 0,
            "compute_edges": 4,
            "compute_vertices_applied": 4,
            "compute_memory_requests": 16,
            "source_map_operations": 4,
            "reduce_operations": 8,
            "apply_operations": 4,
            "edge_axis_transfers": 24,
            "value_axis_transfers": 5,
            "backend_requests": 90,
        }
        dram = {"dram_reads": 70, "dram_writes": 20, "dram_channels": 32}
        self.assertEqual(
            validate_full_pagerank_result(result, dram, channels=32), []
        )

    def test_full_pagerank_result_rejects_wrong_rank(self) -> None:
        result = {
            "success": True,
            "mode": "spine_pagerank",
            "timing_evidence": "provisional_algorithm_pipeline",
            "vertices": 4,
            "input_edges": 4,
            "pagerank_iterations": 2,
            "pagerank_completed_iterations": 2,
            "iteration_cycles": [100, 80],
            "correctness_mismatches": 0,
            "max_abs_error": 0.0,
            "ranks": [0.25, 0.25, 0.25, 0.25],
            "reference_ranks": [0.25, 0.25, 0.25, 0.25],
            "rank_sum": 1.0,
            "maintenance_persisted_edges": 4,
            "maintenance_cycles": 50,
            "reader_edges": 4,
            "reader_graph_payload_bytes": 64,
            "reader_source_requests": 4,
            "reader_source_responses": 4,
            "reader_source_windows": 1,
            "reader_protocol_status": 0,
            "compute_edges": 4,
            "compute_vertices_applied": 4,
            "compute_memory_requests": 16,
            "source_map_operations": 4,
            "reduce_operations": 8,
            "apply_operations": 4,
            "edge_axis_transfers": 24,
            "value_axis_transfers": 5,
            "backend_requests": 90,
        }
        dram = {"dram_reads": 70, "dram_writes": 20, "dram_channels": 32}
        self.assertIn(
            "known_two_iteration_result",
            validate_full_pagerank_result(result, dram, channels=32),
        )

    def test_compute_only_result_skips_maintenance_profile(self) -> None:
        expected = {"maintenance_count_scan_ii": 1}
        self.assertTrue(
            maintenance_timing_profile_matches(
                {"mode": "spine_compute"}, expected
            )
        )
        self.assertFalse(
            maintenance_timing_profile_matches(
                {"mode": "spine_vertical"}, expected
            )
        )

    def test_matching_architecture_and_dram_counts_pass(self) -> None:
        result = {
            "success": True,
            "mode": "spine_vertical",
            "spine_axi_profile": "hls_split_9c08763",
            "correctness_mismatches": 0,
            "frontier_mismatches": 0,
            "next_active": 10,
            "maintenance_scan_passes": 20,
            "maintenance_edge_visits": 200,
            "maintenance_sorted_bytes": 3_200,
            "maintenance_sorted_payload_read_bytes": 3_200,
            "maintenance_sorted_read_beats": 200,
            "maintenance_sorted_axi_read_beats_streamed": 200,
            "maintenance_max_scan_buffered_edges": 10,
            "maintenance_dirty_validate_visits": 10,
            "maintenance_dirty_mark_visits": 10,
            "maintenance_dirty_unique_sources": 1,
            "maintenance_dirty_bitmap_reads": 1,
            "maintenance_dirty_bitmap_writes": 1,
            "maintenance_dirty_list_reads": 1,
            "maintenance_dirty_list_appends": 1,
            "maintenance_dirty_duplicates_suppressed": 9,
            "maintenance_dirty_generation_advances": 1,
            "maintenance_dirty_count": 1,
            "maintenance_dirty_generation": 1,
            "maintenance_hot_cold_count_visits": 10,
            "maintenance_family_precount_visits": 160,
            "maintenance_l0_write_visits": 10,
            "reader_tiles": 5,
            "reader_edges": 10,
            "reader_graph_bytes": 184,
            "maintenance_graph_index_payload_write_bytes": 64,
            "maintenance_graph_payload_write_bytes": 80,
            "maintenance_page_list_payload_write_bytes": 8,
            "maintenance_page_list_count_write_bytes": 128,
            "reader_graph_index_payload_bytes": 24,
            "reader_graph_payload_bytes": 160,
            "reader_construction_payload_bytes": 80,
            "reader_replay_payload_bytes": 80,
            "reader_graph_index_bitmap_misses": 0,
            "reader_range_path": 1,
            "reader_range_error": 0,
            "reader_range_fallback_reason": 0,
            "reader_range_tasks": 5,
            "reader_range_row_lookups": 1,
            "reader_range_active_records": 1,
            "reader_range_family_probes": 16,
            "reader_range_family_skips": 0,
            "reader_range_level_checks": 176,
            "reader_range_construction_payloads": 10,
            "reader_range_replay_payloads": 10,
            "reader_range_clear_cycles": 256,
            "reader_range_prefix_cycles": 256,
            "reader_range_scatter_cycles": 5,
            "reader_range_verify_cycles": 256,
            "reader_metadata_bytes": 2_928,
            "reader_dirty_list_bytes": 16,
            "reader_dirty_bitmap_bytes": 16,
            "reader_active_bin_bytes": 0,
            "reader_source_requests": 1,
            "reader_source_responses": 1,
            "reader_source_windows": 1,
            "reader_protocol_markers": 3,
            "reader_protocol_acks": 1,
            "reader_protocol_status": 0,
            "reader_dirty_status": 0,
            "reader_metadata_write_bytes": 16,
            "reader_result_write_bytes": 64,
            "reader_diagnostic_words": 10,
            "reader_done_words": 1,
            "reader_done_overflow": 0,
            "compute_protocol_markers": 3,
            "compute_protocol_acks": 1,
            "compute_protocol_status": 0,
            "compute_diagnostic_words": 10,
            "compute_done_words": 1,
            "compute_done_overflow": 0,
            "compute_range_path": 1,
            "compute_range_fallback_reason": 0,
            "compute_range_error": 0,
            "compute_range_tasks": 5,
            "compute_range_row_lookups": 1,
            "compute_range_construction_payloads": 10,
            "compute_range_replay_payloads": 10,
            "compute_range_active_records": 1,
            "compute_range_family_probes": 16,
            "compute_range_family_skips": 0,
            "compute_dirty_count": 1,
            "compute_dirty_generation": 1,
            "reader_page_epoch_misses": 0,
            "reader_occupied_levels": 1,
            "compute_fast_tiles": 5,
            "compute_full_tiles": 0,
            "compute_processed_edges": 10,
            "edge_axis_transfers": 35,
            "edge_axis_max_occupancy": 15,
            "value_axis_transfers": 2,
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
            "reader_metadata_bytes": 2_928,
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
            "reader_metadata_bytes": 2_928,
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
            "spine_axi_profile": "hls_split_9c08763",
            "correctness_mismatches": 0,
            "frontier_mismatches": 0,
            "next_active": 3,
            "input_edges": 2,
            "preload_edges": 1,
            "maintenance_start_cycle": 1,
            "maintenance_end_cycle": 501,
            "maintenance_cycles": 500,
            "maintenance_target_level": 1,
            "maintenance_hot_target_level": 0,
            "maintenance_cold_input_edges": 1,
            "maintenance_hot_input_edges": 1,
            "maintenance_scan_passes": 36,
            "maintenance_edge_visits": 72,
            "maintenance_sorted_bytes": 1_184,
            "maintenance_sorted_payload_read_bytes": 1_184,
            "maintenance_sorted_read_beats": 72,
            "maintenance_sorted_axi_read_beats_streamed": 72,
            "maintenance_max_scan_buffered_edges": 2,
            "maintenance_dirty_validate_visits": 2,
            "maintenance_dirty_mark_visits": 2,
            "maintenance_dirty_unique_sources": 1,
            "maintenance_dirty_bitmap_reads": 1,
            "maintenance_dirty_bitmap_writes": 1,
            "maintenance_dirty_list_reads": 1,
            "maintenance_dirty_list_appends": 1,
            "maintenance_dirty_duplicates_suppressed": 1,
            "maintenance_dirty_generation_advances": 1,
            "maintenance_dirty_count": 1,
            "maintenance_dirty_generation": 1,
            "maintenance_hot_cold_count_visits": 2,
            "maintenance_family_precount_visits": 64,
            "maintenance_l0_write_visits": 2,
            "maintenance_carry_payload_reads": 1,
            "maintenance_carry_payload_read_bytes": 8,
            "maintenance_carry_new_batch_reads": 2,
            "maintenance_carry_new_batch_read_bytes": 32,
            "maintenance_carry_refill_wait_cycles": 11,
            "maintenance_carry_cursor_metadata_read_bytes": 96,
            "maintenance_carry_cursor_page_ids": 1,
            "maintenance_carry_cursor_pages_visited": 1,
            "maintenance_carry_cursor_bitmap_words": 4,
            "maintenance_carry_cursor_bits_inspected": 256,
            "maintenance_carry_cursor_refill_cycles": 261,
            "maintenance_carry_cursor_rows_entered": 1,
            "maintenance_carry_cursor_row_offset_reads": 2,
            "maintenance_carry_cursor_validation_failures": 0,
            "maintenance_carry_writer_groups_seen": 2,
            "maintenance_carry_writer_groups_emitted": 2,
            "maintenance_carry_writer_groups_cancelled": 0,
            "maintenance_carry_writer_edge_word_writes": 2,
            "maintenance_carry_writer_row_word_writes": 1,
            "maintenance_carry_writer_mask_word_writes": 1,
            "maintenance_carry_writer_page_base_word_writes": 2,
            "maintenance_carry_writer_bitmap_page_writes": 1,
            "maintenance_carry_writer_page_list_word_writes": 1,
            "maintenance_carry_writer_page_epoch_word_writes": 1,
            "maintenance_carry_writer_memory_wait_cycles": 9,
            "maintenance_carry_max_buffered_heads": 2,
            "maintenance_carry_merge_inputs": 2,
            "maintenance_carry_outputs": 2,
            "reader_tiles": 1,
            "reader_edges": 3,
            "reader_graph_bytes": 96,
            "maintenance_graph_index_payload_write_bytes": 128,
            "maintenance_graph_payload_write_bytes": 24,
            "maintenance_page_list_payload_write_bytes": 16,
            "maintenance_page_list_count_write_bytes": 320,
            "reader_graph_index_payload_bytes": 48,
            "reader_graph_payload_bytes": 48,
            "reader_construction_payload_bytes": 24,
            "reader_replay_payload_bytes": 24,
            "reader_graph_index_bitmap_misses": 0,
            "reader_range_path": 1,
            "reader_range_error": 0,
            "reader_range_fallback_reason": 0,
            "reader_range_tasks": 2,
            "reader_range_row_lookups": 2,
            "reader_range_active_records": 1,
            "reader_range_family_probes": 32,
            "reader_range_family_skips": 0,
            "reader_range_level_checks": 352,
            "reader_range_construction_payloads": 3,
            "reader_range_replay_payloads": 3,
            "reader_metadata_bytes": 3_000,
            "reader_dirty_list_bytes": 16,
            "reader_dirty_bitmap_bytes": 16,
            "reader_active_bin_bytes": 0,
            "reader_source_requests": 1,
            "reader_source_responses": 1,
            "reader_source_windows": 1,
            "reader_protocol_markers": 3,
            "reader_protocol_acks": 1,
            "reader_protocol_status": 0,
            "reader_dirty_status": 0,
            "reader_metadata_write_bytes": 16,
            "reader_result_write_bytes": 64,
            "reader_diagnostic_words": 10,
            "reader_done_words": 1,
            "reader_done_overflow": 0,
            "compute_protocol_markers": 3,
            "compute_protocol_acks": 1,
            "compute_protocol_status": 0,
            "compute_diagnostic_words": 10,
            "compute_done_words": 1,
            "compute_done_overflow": 0,
            "compute_range_path": 1,
            "compute_range_fallback_reason": 0,
            "compute_range_error": 0,
            "compute_range_tasks": 2,
            "compute_range_row_lookups": 2,
            "compute_range_construction_payloads": 3,
            "compute_range_replay_payloads": 3,
            "compute_range_active_records": 1,
            "compute_range_family_probes": 32,
            "compute_range_family_skips": 0,
            "compute_dirty_count": 1,
            "compute_dirty_generation": 1,
            "reader_page_epoch_misses": 0,
            "reader_occupied_levels": 2,
            "reader_cold_edges": 2,
            "reader_hot_edges": 1,
            "compute_fast_tiles": 1,
            "compute_full_tiles": 0,
            "compute_processed_edges": 3,
            "edge_axis_transfers": 20,
            "edge_axis_max_occupancy": 5,
            "value_axis_transfers": 2,
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
            "spine_axi_profile": "hls_split_9c08763",
            "converged": True,
            "correctness_mismatches": 0,
            "frontier_mismatches": 0,
            "input_edges": 8,
            "rounds": 6,
            "final_values": [0, 3, 2, 7, 8, 10],
            "frontier_in_sizes": [1, 3, 2, 2, 2, 1],
            "frontier_out_sizes": [3, 2, 2, 2, 1, 0],
            "processed_edges_per_round": [8, 3, 2, 2, 1, 0],
            "maintenance_scan_passes": 20,
            "maintenance_edge_visits": 160,
            "maintenance_sorted_bytes": 2_560,
            "maintenance_sorted_payload_read_bytes": 2_560,
            "maintenance_sorted_read_beats": 160,
            "maintenance_sorted_axi_read_beats_streamed": 160,
            "maintenance_max_scan_buffered_edges": 8,
            "maintenance_dirty_validate_visits": 8,
            "maintenance_dirty_mark_visits": 8,
            "maintenance_dirty_unique_sources": 5,
            "maintenance_dirty_bitmap_reads": 5,
            "maintenance_dirty_bitmap_writes": 5,
            "maintenance_dirty_list_reads": 5,
            "maintenance_dirty_list_appends": 5,
            "maintenance_dirty_duplicates_suppressed": 3,
            "maintenance_dirty_generation_advances": 1,
            "maintenance_dirty_count": 5,
            "maintenance_dirty_generation": 1,
            "maintenance_hot_cold_count_visits": 8,
            "maintenance_family_precount_visits": 128,
            "maintenance_l0_write_visits": 8,
            "round_cycles": [10, 11, 12, 13, 14, 15],
            "edge_axis_max_occupancy_per_round": [5, 6, 5, 5, 4, 2],
            "edge_axis_push_stalls_per_round": [0, 1, 0, 0, 0, 0],
            "fast_tiles_per_round": [1, 1, 1, 1, 1, 0],
            "full_tiles_per_round": [0, 0, 0, 0, 0, 0],
            "reader_metadata_bytes_per_round": [2960, 3232, 3232, 3232, 3224, 3216],
            "reader_metadata_write_bytes_per_round": [16, 16, 16, 16, 16, 16],
            "reader_result_write_bytes_per_round": [64, 64, 64, 64, 64, 64],
            "reader_source_sizes_per_round": [5, 2, 2, 2, 1, 0],
            "reader_source_requests_per_round": [5, 0, 0, 0, 0, 0],
            "reader_source_responses_per_round": [5, 0, 0, 0, 0, 0],
            "reader_source_windows_per_round": [1, 0, 0, 0, 0, 0],
            "reader_protocol_markers_per_round": [3, 0, 0, 0, 0, 0],
            "reader_protocol_acks_per_round": [1, 0, 0, 0, 0, 0],
            "reader_protocol_status_per_round": [0, 0, 0, 0, 0, 0],
            "reader_dirty_status_per_round": [0, 0, 0, 0, 0, 0],
            "reader_dirty_counts_per_round": [5, 0, 0, 0, 0, 0],
            "reader_dirty_generations_per_round": [1, 2, 2, 2, 2, 2],
            "reader_ack_eligible_per_round": [1, 0, 0, 0, 0, 0],
            "reader_host_coverage_match_per_round": [0, 0, 0, 0, 0, 0],
            "compute_protocol_status_per_round": [0, 0, 0, 0, 0, 0],
            "reader_dirty_list_bytes_per_round": [80, 0, 0, 0, 0, 0],
            "reader_dirty_bitmap_bytes_per_round": [80, 0, 0, 0, 0, 0],
            "reader_active_bin_bytes_per_round": [0, 64, 64, 64, 32, 0],
            "reader_epoch_misses_per_round": [0, 0, 0, 0, 0, 0],
            "edge_axis_transfers_per_round": [29, 16, 15, 15, 14, 11],
            "value_axis_transfers_per_round": [6, 0, 0, 0, 0, 0],
            "value_axis_max_occupancy_per_round": [5, 0, 0, 0, 0, 0],
            "maintenance_graph_index_payload_write_bytes": 88,
            "maintenance_graph_payload_write_bytes": 64,
            "maintenance_page_list_payload_write_bytes": 8,
            "maintenance_page_list_count_write_bytes": 128,
            "reader_graph_index_payload_bytes_per_round": [136, 56, 64, 56, 24, 0],
            "reader_graph_payload_bytes_per_round": [128, 48, 32, 32, 16, 0],
            "reader_construction_payload_bytes_per_round": [64, 24, 16, 16, 8, 0],
            "reader_replay_payload_bytes_per_round": [64, 24, 16, 16, 8, 0],
            "reader_graph_index_bitmap_misses_per_round": [0, 0, 0, 0, 0, 0],
            "reader_range_tasks_per_round": [5, 2, 2, 2, 1, 0],
            "reader_range_row_lookups_per_round": [5, 2, 2, 2, 1, 0],
            "reader_range_level_checks_per_round": [880, 22, 22, 22, 11, 0],
            "reader_range_construction_payloads_per_round": [8, 3, 2, 2, 1, 0],
            "reader_range_replay_payloads_per_round": [8, 3, 2, 2, 1, 0],
            "reader_range_active_records_per_round": [5, 2, 2, 2, 1, 0],
            "reader_range_family_probes_per_round": [80, 2, 2, 2, 1, 0],
            "reader_range_family_skips_per_round": [0, 0, 0, 0, 0, 0],
            "reader_range_paths_per_round": [1, 1, 1, 1, 1, 1],
            "reader_range_fallback_reasons_per_round": [0, 0, 0, 0, 0, 0],
            "reader_range_errors_per_round": [0, 0, 0, 0, 0, 0],
            "reader_diagnostic_words_per_round": [10, 10, 10, 10, 10, 10],
            "reader_done_words_per_round": [1, 1, 1, 1, 1, 1],
            "reader_done_overflow_per_round": [0, 0, 0, 0, 0, 0],
            "compute_diagnostic_words_per_round": [10, 10, 10, 10, 10, 10],
            "compute_done_words_per_round": [1, 1, 1, 1, 1, 1],
            "compute_done_overflow_per_round": [0, 0, 0, 0, 0, 0],
            "compute_range_paths_per_round": [1, 1, 1, 1, 1, 1],
            "compute_range_fallback_reasons_per_round": [0, 0, 0, 0, 0, 0],
            "compute_range_errors_per_round": [0, 0, 0, 0, 0, 0],
            "compute_range_tasks_per_round": [5, 2, 2, 2, 1, 0],
            "compute_range_row_lookups_per_round": [5, 2, 2, 2, 1, 0],
            "compute_range_construction_payloads_per_round": [8, 3, 2, 2, 1, 0],
            "compute_range_replay_payloads_per_round": [8, 3, 2, 2, 1, 0],
            "compute_range_active_records_per_round": [5, 2, 2, 2, 1, 0],
            "compute_range_family_probes_per_round": [80, 2, 2, 2, 1, 0],
            "compute_range_family_skips_per_round": [0, 0, 0, 0, 0, 0],
            "compute_dirty_counts_per_round": [5, 0, 0, 0, 0, 0],
            "compute_dirty_generations_per_round": [1, 2, 2, 2, 2, 2],
            "dirty_ack_started": 1,
            "dirty_ack_status": 0,
            "dirty_ack_cycles": 10,
            "dirty_ack_captured_count": 5,
            "dirty_ack_captured_generation": 1,
            "dirty_ack_result_count": 0,
            "dirty_ack_result_generation": 2,
            "dirty_ack_candidate_write_bytes": 40,
            "dirty_ack_metadata_read_bytes": 72,
            "dirty_ack_metadata_write_bytes": 64,
            "dirty_ack_list_read_bytes": 160,
            "dirty_ack_bitmap_read_bytes": 160,
            "dirty_ack_bitmap_write_bytes": 80,
            "dirty_ack_validated_sources": 5,
            "dirty_ack_cleared_sources": 5,
            "dirty_ack_generation_advances": 1,
            "backend_requests": 100,
        }
        dram = {"dram_reads": 60, "dram_writes": 40, "dram_channels": 32}
        self.assertEqual(
            validate_multiround_sssp_result(result, dram, channels=32), []
        )

    def test_source_protocol_window_structure_passes(self) -> None:
        result = {
            "success": True,
            "mode": "spine_vertical",
            "correctness_mismatches": 0,
            "frontier_mismatches": 0,
            "input_edges": 17,
            "next_active": 1,
            "reader_source_requests": 17,
            "reader_source_responses": 17,
            "reader_source_windows": 2,
            "reader_protocol_markers": 3,
            "reader_protocol_acks": 1,
            "reader_protocol_status": 0,
            "reader_dirty_status": 0,
            "reader_metadata_write_bytes": 16,
            "reader_result_write_bytes": 64,
            "reader_diagnostic_words": 10,
            "reader_done_words": 1,
            "reader_done_overflow": 0,
            "compute_protocol_markers": 3,
            "compute_protocol_acks": 1,
            "compute_protocol_status": 0,
            "compute_diagnostic_words": 10,
            "compute_done_words": 1,
            "compute_done_overflow": 0,
            "reader_range_path": 1,
            "reader_range_fallback_reason": 0,
            "reader_range_error": 0,
            "reader_range_tasks": 17,
            "reader_range_row_lookups": 17,
            "reader_range_construction_payloads": 17,
            "reader_range_replay_payloads": 17,
            "reader_range_active_records": 17,
            "reader_range_family_probes": 272,
            "reader_range_family_skips": 0,
            "compute_range_path": 1,
            "compute_range_fallback_reason": 0,
            "compute_range_error": 0,
            "compute_range_tasks": 17,
            "compute_range_row_lookups": 17,
            "compute_range_construction_payloads": 17,
            "compute_range_replay_payloads": 17,
            "compute_range_active_records": 17,
            "compute_range_family_probes": 272,
            "compute_range_family_skips": 0,
            "compute_dirty_count": 17,
            "compute_dirty_generation": 1,
            "edge_axis_transfers": 50,
            "value_axis_transfers": 18,
            "edge_axis_max_occupancy": 13,
            "value_axis_max_occupancy": 2,
            "backend_requests": 100,
        }
        dram = {"dram_reads": 60, "dram_writes": 40, "dram_channels": 32}
        self.assertEqual(
            validate_protocol_window_result(result, dram, channels=32), []
        )

    def test_frozen_fallback_evidence_passes(self) -> None:
        cases = (
            ("sst_spine_fallback_capacity_20260724_summary.json", 2),
            ("sst_spine_fallback_payload_20260724_summary.json", 3),
        )
        for filename, reason in cases:
            with self.subTest(filename=filename):
                summary = json.loads(
                    (ROOT / "docs" / "evidence" / filename).read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    validate_fallback_result(
                        summary, summary, channels=32, expected_reason=reason
                    ),
                    [],
                )


if __name__ == "__main__":
    unittest.main()
