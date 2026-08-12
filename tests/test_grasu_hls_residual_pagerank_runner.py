from __future__ import annotations

from pathlib import Path
import unittest

from scripts.run_sst_grasu_regraph_hls_residual_pagerank import (
    DEFAULT_CAPABILITY_CATALOG,
    DEFAULT_PROFILE,
    compact_hls_residual_oracle,
    external_rank_oracle_matches,
    frontier_ledger_matches,
    propagation_iteration_count_matches,
    require_hls_residual_capability,
    residual_bound_matches,
    validate_update_only_result,
)
from scripts.run_sst_grasu_regraph_hls_pagerank import full_pagerank_oracle
from scripts.run_sst_grasu_regraph_hls_weighted import build_hls_weighted_oracle
from spine_cycle_sim.experiments.regraph_contracts import (
    expected_partitioned_source_cache_requests,
)
from spine_cycle_sim.experiments.shared_workloads import load_slice


ROOT = Path(__file__).resolve().parents[1]


class GraSuHlsResidualPageRankRunnerTests(unittest.TestCase):
    def test_pinned_capability_is_thresholded_and_simulation_only(self) -> None:
        _catalog, capability = require_hls_residual_capability(
            DEFAULT_PROFILE.resolve(), DEFAULT_CAPABILITY_CATALOG.resolve()
        )
        self.assertEqual(capability.evidence_tier, "simulation_only")
        self.assertEqual(
            capability.convergence,
            "signed_residual_threshold_or_iteration_limit",
        )

    def test_mathematical_oracle_uses_final_external_graph(self) -> None:
        initial = load_slice(
            ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_initial.slice"
        )
        update = load_slice(
            ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_update.slice"
        )
        prepared = build_hls_weighted_oracle(initial, update, 0)
        ranks = full_pagerank_oracle(
            initial.vertices, prepared.final_external_edges, 0.85, 200
        )
        self.assertEqual(len(ranks), initial.vertices)
        self.assertAlmostEqual(sum(ranks), 1.0, places=12)
        self.assertGreater(prepared.physical_updates, prepared.logical_updates)

    def test_runtime_oracle_preserves_source_request_ledger_without_edges(self) -> None:
        initial = load_slice(
            ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_initial.slice"
        )
        update = load_slice(
            ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_update.slice"
        )
        prepared = build_hls_weighted_oracle(initial, update, 0)
        partition_vertices = 4
        source_buffer_vertices = 4
        compact = compact_hls_residual_oracle(
            prepared, partition_vertices, source_buffer_vertices
        )
        partitions = (initial.vertices + partition_vertices - 1) // partition_vertices
        sources: list[set[int]] = [set() for _ in range(partitions)]
        for source, destination, _weight in prepared.final_internal_edges:
            sources[destination // partition_vertices].add(source)
        expected = sum(
            expected_partitioned_source_cache_requests(
                partition_sources, source_buffer_vertices, 1
            )
            for partition_sources in sources
        )
        self.assertEqual(compact.source_requests_per_iteration, expected)
        self.assertEqual(compact.external_to_internal, prepared.external_to_internal)
        self.assertEqual(compact.internal_to_external, prepared.internal_to_external)
        self.assertFalse(hasattr(compact, "final_internal_edges"))

    def test_update_only_requires_degree_rmw_observability(self) -> None:
        initial = load_slice(
            ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_initial.slice"
        )
        update = load_slice(
            ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_update.slice"
        )
        prepared = build_hls_weighted_oracle(initial, update, 0)
        compact = compact_hls_residual_oracle(prepared, 4, 4)
        result = {
            "success": True,
            "mode": "grasu_regraph_hls_weighted_residual_pagerank",
            "measurement_window": "pure_update_only",
            "pipeline_order": "update_only_no_regraph_compute",
            "conversion_cost_included": False,
            "logical_updates": compact.logical_updates,
            "physical_updates": compact.physical_updates,
            "update_cycles": 199,
            "compute_cycles": 0,
            "update_state_match": True,
            "memory_locality_ledger_match": True,
            "correctness_mismatches": 0,
            "update_observability": {
                "updates": compact.physical_updates,
                "degree_reads": compact.physical_updates,
                "degree_writes": compact.physical_updates,
            },
        }
        validate_update_only_result(result, compact)
        result["update_observability"]["degree_writes"] = 0
        with self.assertRaises(RuntimeError):
            validate_update_only_result(result, compact)

    def test_delta_validator_accepts_linf_when_l1_exceeds_epsilon(self) -> None:
        result = {"residual_l1": 3.6e-4, "residual_linf": 9.0e-5}
        self.assertTrue(
            residual_bound_matches(
                result, "deltahls_sink_free_linf_warm", 1.0e-4
            )
        )
        self.assertFalse(
            residual_bound_matches(result, "generic_dangling_l1_cold", 1.0e-4)
        )

    def test_hardware_warm_validator_uses_direct_linf_threshold(self) -> None:
        result = {"residual_l1": 3.6e-4, "residual_linf": 9.0e-5}
        self.assertTrue(
            residual_bound_matches(
                result, "grasu_hardware_warm_dangling_linf", 1.0e-4
            )
        )

    def test_delta_rank_oracle_uses_fixed_point_defect_bound(self) -> None:
        result = {
            "old_rank_l1": 3.0e-5,
            "residual_l1": 4.0e-5,
            "mathematical_max_abs_error": 2.0e-5,
            "mathematical_error_tolerance": 1.1 * 7.0e-5 / 0.15,
            "mathematical_error_bound": (
                "l1_fixed_point_defect_plus_final_residual_over_one_minus_d"
            ),
        }
        self.assertTrue(
            external_rank_oracle_matches(
                result,
                2.0e-5,
                "deltahls_sink_free_linf_warm",
                1.0e-6,
                0.85,
            )
        )

    def test_delta_rank_oracle_rejects_wrong_bound_label(self) -> None:
        result = {
            "old_rank_l1": 3.0e-5,
            "residual_l1": 4.0e-5,
            "mathematical_max_abs_error": 2.0e-5,
            "mathematical_error_tolerance": 1.1 * 7.0e-5 / 0.15,
            "mathematical_error_bound": "epsilon_over_vertices",
        }
        self.assertFalse(
            external_rank_oracle_matches(
                result,
                2.0e-5,
                "deltahls_sink_free_linf_warm",
                1.0e-6,
                0.85,
            )
        )

    def test_hardware_warm_rank_oracle_has_float32_rounding_floor(self) -> None:
        result = {
            "old_rank_l1": 0.0,
            "residual_l1": 0.0,
            "mathematical_max_abs_error": 2.0e-8,
            "mathematical_error_tolerance": 5.0e-7,
            "mathematical_error_bound": (
                "l1_fixed_point_defect_plus_final_residual_over_one_minus_d"
            ),
        }
        self.assertTrue(
            external_rank_oracle_matches(
                result,
                2.0e-8,
                "grasu_hardware_warm_dangling_linf",
                1.0e-6,
                0.85,
            )
        )

    def test_generic_rank_oracle_keeps_five_epsilon_gate(self) -> None:
        self.assertTrue(
            external_rank_oracle_matches(
                {}, 4.9e-4, "generic_dangling_l1_cold", 1.0e-4, 0.85
            )
        )
        self.assertFalse(
            external_rank_oracle_matches(
                {}, 5.1e-4, "generic_dangling_l1_cold", 1.0e-4, 0.85
            )
        )

    def test_hardware_warm_correction_only_execution_has_empty_frontier(self) -> None:
        self.assertTrue(propagation_iteration_count_matches(0, 256, True))
        self.assertTrue(
            frontier_ledger_matches(
                {"frontier_in_sizes": [], "frontier_out_sizes": []}, 0
            )
        )

    def test_generic_residual_requires_a_propagation_round(self) -> None:
        self.assertFalse(propagation_iteration_count_matches(0, 256, False))
        self.assertFalse(
            frontier_ledger_matches(
                {"frontier_in_sizes": [1], "frontier_out_sizes": []}, 1
            )
        )


if __name__ == "__main__":
    unittest.main()
