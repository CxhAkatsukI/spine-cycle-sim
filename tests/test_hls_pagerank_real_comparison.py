from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.hls_pagerank_real_comparison import (
    pair_row,
    rank_vector,
    system_row,
    validate_grasu_pagerank_result,
    validate_spine_pagerank_result,
)


def _run() -> dict[str, object]:
    return {
        "run_id": "real_test_weight_change_u8",
        "dataset_id": "test",
        "dataset_kind": "real_compact_slice",
        "scenario": "weight_change",
        "graph": {"vertices": 4, "records": 4},
        "user_mutations": 8,
        "physical_records": 16,
        "final_edges": 4,
    }


class HlsPageRankRealComparisonTests(unittest.TestCase):
    def test_rank_vector_rejects_missing_and_nonfinite_values(self) -> None:
        self.assertEqual(rank_vector([0.25, 0.75]), (0.25, 0.75))
        with self.assertRaises(ValueError):
            rank_vector([])
        with self.assertRaises(ValueError):
            rank_vector([float("nan")])

    def test_spine_validation_requires_dynamic_phase_ledgers(self) -> None:
        result = {
            "success": True,
            "status": "PASS",
            "mode": "spine_pagerank",
            "architecture_profile_id": "spine",
            "core_mhz": 141.0,
            "dynamic_update": True,
            "pipeline_order": (
                "zero_time_l0_preload_then_update_maintenance_then_compute"
            ),
            "vertices": 4,
            "initial_edges": 4,
            "update_edges": 16,
            "materialized_snapshot_edges": 4,
            "maintenance_persisted_edges": 4,
            "pagerank_iterations": 3,
            "pagerank_completed_iterations": 3,
            "iteration_cycles": [100, 100, 100],
            "pagerank_damping": 0.85,
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "correctness_mismatches": 0,
            "max_abs_error": 1.0e-7,
            "mathematical_max_abs_error": 2.0e-7,
            "ranks": [0.25] * 4,
            "cycles": 400,
            "maintenance_cycles": 100,
            "maintenance_backend_requests": 10,
            "compute_backend_requests": 30,
            "backend_requests": 40,
            "dram_reads": 25,
            "dram_writes": 15,
        }
        arguments = dict(
            expected_profile_id="spine",
            expected_core_mhz=141.0,
            iterations=3,
            damping=0.85,
        )
        self.assertEqual(
            validate_spine_pagerank_result(_run(), result, **arguments), []
        )
        result["compute_backend_requests"] = 29
        self.assertIn(
            "backend_window",
            validate_spine_pagerank_result(_run(), result, **arguments),
        )

    def test_grasu_validation_requires_degree_and_compute_ledgers(self) -> None:
        child = {
            "status": "PASS",
            "profile_sha256": "profile-hash",
            "result": {
                "success": True,
                "mode": "grasu_regraph_hls_weighted_pagerank",
                "claim_class": (
                    "hls_equivalent_proposed_execution_driven_simulation"
                ),
                "pipeline_order": (
                    "update_then_degree_barrier_then_pma_native_compute"
                ),
                "core_mhz": 200.0,
                "vertices": 4,
                "initial_edges": 4,
                "logical_updates": 16,
                "physical_updates": 16,
                "iterations": 3,
                "pagerank_damping": 0.85,
                "compute_live_edges": 12,
                "architecture_correctness_mismatches": 0,
                "mathematical_correctness_mismatches": 0,
                "correctness_mismatches": 0,
                "max_abs_error": 1.0e-7,
                "mathematical_max_abs_error": 2.0e-7,
                "ranks_external": [0.25] * 4,
                "cycles": 400,
                "update_cycles": 100,
                "compute_cycles": 300,
                "update_pma_reads": 16,
                "update_pma_writes": 16,
                "degree_update_reads": 16,
                "degree_update_writes": 16,
                "update_backend_requests": 10,
                "compute_backend_requests": 30,
                "backend_requests": 40,
                "expected_backend_requests": 40,
            },
            "dram": {"reads": 25, "writes": 15},
        }
        arguments = dict(
            expected_profile_sha256="profile-hash",
            expected_core_mhz=200.0,
            iterations=3,
            damping=0.85,
        )
        self.assertEqual(
            validate_grasu_pagerank_result(_run(), child, **arguments), []
        )
        child["result"]["degree_update_reads"] = 15
        self.assertIn(
            "update_ledger",
            validate_grasu_pagerank_result(_run(), child, **arguments),
        )

    def test_pair_uses_profile_time_and_tolerant_external_ranks(self) -> None:
        common = {
            "run_id": "r",
            "dataset_id": "d",
            "scenario": "insert",
            "user_mutations": 8,
            "physical_records": 8,
            "backend_requests": 100,
            "update_backend_requests": 10,
            "compute_backend_requests": 90,
            "ranks": (0.2, 0.8),
        }
        spine = {
            **common,
            "e2e_ms": 2.0,
            "update_ms": 0.5,
            "compute_ms": 1.5,
        }
        grasu = {
            **common,
            "e2e_ms": 4.0,
            "update_ms": 0.1,
            "compute_ms": 3.9,
            "backend_requests": 200,
            "update_backend_requests": 20,
            "compute_backend_requests": 180,
            "ranks": (0.200001, 0.799999),
        }
        pair = pair_row(spine, grasu)
        self.assertEqual(pair["spine_speedup_over_grasu_e2e"], 2.0)
        self.assertTrue(pair["cross_system_ranks_match"])
        broken = {**grasu, "ranks": (0.3, 0.7)}
        with self.assertRaisesRegex(ValueError, "rank mismatch"):
            pair_row(spine, broken)

    def test_system_row_reports_update_and_compute_memory(self) -> None:
        result = {
            "cycles": 400,
            "maintenance_cycles": 100,
            "maintenance_backend_requests": 10,
            "compute_backend_requests": 30,
            "backend_requests": 40,
            "ranks": [0.25] * 4,
            "edge_axis_push_stalls": 0,
            "core_mhz": 200.0,
            "correctness_mismatches": 0,
        }
        dram = {
            "reads": 25,
            "writes": 15,
            "activates": 5,
            "precharges": 4,
            "total_energy_pj": 100.0,
        }
        row = system_row(
            _run(),
            system="spine",
            result=result,
            dram=dram,
            wall_seconds=1.0,
            profile_id="spine",
        )
        self.assertEqual(row["e2e_ms"], 0.002)
        self.assertEqual(row["update_backend_bytes"], 640)
        self.assertEqual(row["compute_backend_bytes"], 1920)


if __name__ == "__main__":
    unittest.main()
