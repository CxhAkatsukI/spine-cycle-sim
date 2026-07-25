from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.hls_real_comparison import (
    distance_vector_sha256,
    expected_spine_update_path,
    normalized_distances,
    pair_row,
    validate_grasu_hls_result,
    validate_spine_dynamic_result,
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
        "hls_host_supersteps": 4,
    }


class HlsRealComparisonTests(unittest.TestCase):
    def test_update_path_is_fail_closed(self) -> None:
        self.assertEqual(expected_spine_update_path("insert"), "incremental_relax")
        self.assertEqual(expected_spine_update_path("delete"), "full_rebuild")
        self.assertEqual(expected_spine_update_path("weight_change"), "full_rebuild")
        with self.assertRaises(ValueError):
            expected_spine_update_path("mixed")

    def test_distance_sentinels_normalize_across_architectures(self) -> None:
        normalized = normalized_distances([0, 7, 0xFFFFFFFF, 0x7FFFFFFE])
        self.assertEqual(normalized, (0, 7, None, None))
        self.assertEqual(
            distance_vector_sha256(normalized),
            distance_vector_sha256((0, 7, None, None)),
        )

    def test_spine_validation_checks_aligned_phase_ledgers(self) -> None:
        result = {
            "success": True,
            "status": "PASS",
            "mode": "spine_sssp",
            "architecture_profile_id": "spine",
            "core_mhz": 141.0,
            "dynamic_update": True,
            "dynamic_update_path": "full_rebuild",
            "vertices": 4,
            "input_edges": 4,
            "update_edges": 16,
            "materialized_snapshot_edges": 4,
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "correctness_mismatches": 0,
            "cold_correctness_mismatches": 0,
            "cold_mathematical_correctness_mismatches": 0,
            "full_recompute_correctness_mismatches": 0,
            "frontier_mismatches": 0,
            "cold_frontier_mismatches": 0,
            "converged": True,
            "cycles": 300,
            "cold_cycles": 100,
            "update_cycles": 200,
            "maintenance_cycles": 80,
            "backend_requests": 30,
            "cold_backend_requests": 10,
            "update_backend_requests": 20,
            "dram_reads": 18,
            "dram_writes": 12,
            "final_values": [0, 1, 2, 0xFFFFFFFF],
        }
        self.assertEqual(
            validate_spine_dynamic_result(
                _run(), result, expected_profile_id="spine", expected_core_mhz=141.0
            ),
            [],
        )
        result["update_backend_requests"] = 19
        self.assertIn(
            "backend_window",
            validate_spine_dynamic_result(
                _run(), result, expected_profile_id="spine", expected_core_mhz=141.0
            ),
        )

    def test_grasu_validation_checks_physical_and_fixed_round_ledgers(self) -> None:
        child = {
            "status": "PASS",
            "profile_sha256": "profile-hash",
            "result": {
                "success": True,
                "mode": "grasu_regraph_hls_weighted_sssp",
                "core_mhz": 200.0,
                "vertices": 4,
                "initial_edges": 4,
                "logical_updates": 16,
                "physical_updates": 16,
                "architecture_correctness_mismatches": 0,
                "mathematical_correctness_mismatches": 0,
                "correctness_mismatches": 0,
                "fixed_host_supersteps": True,
                "supersteps": 4,
                "cycles": 210,
                "update_cycles": 10,
                "compute_cycles": 200,
                "update_pma_reads": 16,
                "update_pma_writes": 16,
                "backend_requests": 30,
                "distances_external": [0, 1, 2, 0x7FFFFFFE],
            },
            "dram": {"reads": 20, "writes": 10},
        }
        self.assertEqual(
            validate_grasu_hls_result(
                _run(),
                child,
                expected_profile_sha256="profile-hash",
                expected_core_mhz=200.0,
            ),
            [],
        )
        child["result"]["physical_updates"] = 17
        self.assertIn(
            "physical_records",
            validate_grasu_hls_result(
                _run(),
                child,
                expected_profile_sha256="profile-hash",
                expected_core_mhz=200.0,
            ),
        )

    def test_pair_uses_time_not_raw_cycles_and_requires_equal_answers(self) -> None:
        spine = {
            "run_id": "r",
            "dataset_id": "d",
            "scenario": "insert",
            "user_mutations": 8,
            "physical_records": 8,
            "aligned_e2e_ms": 2.0,
            "structure_update_cycles": 141,
            "core_mhz": 141.0,
            "aligned_backend_requests": 10,
            "normalized_distances": (0, 1, None),
        }
        grasu = {
            **spine,
            "aligned_e2e_ms": 3.0,
            "structure_update_cycles": 400,
            "core_mhz": 200.0,
            "aligned_backend_requests": 20,
        }
        pair = pair_row(spine, grasu)
        self.assertEqual(pair["spine_speedup_over_grasu_e2e"], 1.5)
        self.assertEqual(pair["grasu_to_spine_aligned_backend_request_ratio"], 2.0)
        broken = {**grasu, "normalized_distances": (0, 2, None)}
        with self.assertRaisesRegex(ValueError, "distance mismatch"):
            pair_row(spine, broken)


if __name__ == "__main__":
    unittest.main()
