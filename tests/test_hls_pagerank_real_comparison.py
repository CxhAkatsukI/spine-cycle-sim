from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.hls_pagerank_real_comparison import (
    pair_row,
    rank_vector,
    residual_pair_row,
    residual_system_row,
    system_row,
    validate_grasu_pagerank_result,
    validate_grasu_residual_result,
    validate_spine_pagerank_result,
    validate_spine_residual_result,
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


def _locality_group(requests: int, *, first_requests: int = 1) -> dict[str, int]:
    if requests == 0:
        first_requests = 0
    bytes_ = requests * 32
    first_bytes = first_requests * 32
    return {
        "requests": requests,
        "bytes": bytes_,
        "first_requests": first_requests,
        "first_bytes": first_bytes,
        "contiguous_requests": requests - first_requests,
        "contiguous_bytes": bytes_ - first_bytes,
        "repeated_requests": 0,
        "repeated_bytes": 0,
        "discontinuous_requests": 0,
        "discontinuous_bytes": 0,
    }


def _traffic(requests: int, *, first_requests: int = 1) -> dict[str, object]:
    reads = _locality_group(requests, first_requests=first_requests)
    writes = _locality_group(0, first_requests=0)
    return {
        "classification": (
            "per_initiator_and_operation_accepted_backend_request"
        ),
        "address_basis": "logical_channel_and_byte_address",
        "reads": reads,
        "writes": writes,
        "combined": dict(reads),
    }


def _with_traffic(
    result: dict[str, object], *, update_key: str
) -> dict[str, object]:
    update_requests = int(
        result.get(
            "maintenance_backend_requests",
            result.get("update_backend_requests", 0),
        )
    )
    compute_requests = int(result["compute_backend_requests"])
    backend_requests = int(result["backend_requests"])
    result.update(
        {
            "memory_locality_ledger_match": True,
            "backend_traffic": _traffic(backend_requests, first_requests=2),
            update_key: _traffic(update_requests),
            "compute_backend_traffic": _traffic(compute_requests),
        }
    )
    return result


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
        result = _with_traffic(
            result, update_key="maintenance_backend_traffic"
        )
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
        result["compute_backend_requests"] = 30
        result["backend_traffic"]["combined"]["bytes"] += 1  # type: ignore[index,operator]
        self.assertIn(
            "memory_locality",
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
                "gather_reset_cycles": 12,
                "gather_merge_cycles": 24,
                "gather_rows_emitted": 24,
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
        child["result"] = _with_traffic(
            child["result"], update_key="update_backend_traffic"  # type: ignore[arg-type]
        )
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
        child["result"]["degree_update_reads"] = 16
        child["result"].pop("gather_reset_cycles")
        self.assertIn(
            "gather_activity",
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
            "backend_bytes": 3200,
            "update_backend_requests": 10,
            "update_backend_bytes": 320,
            "compute_backend_requests": 90,
            "compute_backend_bytes": 2880,
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
            "backend_bytes": 6400,
            "update_backend_requests": 20,
            "update_backend_bytes": 640,
            "compute_backend_requests": 180,
            "compute_backend_bytes": 5760,
            "ranks": (0.200001, 0.799999),
        }
        pair = pair_row(spine, grasu)
        self.assertEqual(pair["spine_speedup_over_grasu_e2e"], 2.0)
        self.assertEqual(pair["grasu_to_spine_backend_byte_ratio"], 2.0)
        self.assertTrue(pair["cross_system_ranks_match"])
        broken = {**grasu, "ranks": (0.3, 0.7)}
        with self.assertRaisesRegex(ValueError, "rank mismatch"):
            pair_row(spine, broken)

        dense_spine = {
            **spine,
            "input_scope": "synthetic_dense_batch_sweep",
        }
        self.assertEqual(
            pair_row(dense_spine, grasu)["claim_label"],
            "profile_clock_adjusted_synthetic_dense_batch_execution_driven",
        )

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
        result = _with_traffic(
            result, update_key="maintenance_backend_traffic"
        )
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
        self.assertEqual(row["update_backend_bytes"], 320)
        self.assertEqual(row["compute_backend_bytes"], 960)
        self.assertEqual(row["update_backend_nominal_64b_bytes"], 640)
        self.assertEqual(row["compute_backend_nominal_64b_bytes"], 1920)
        self.assertEqual(row["backend_contiguous_byte_ratio"], 1.0)

    def test_residual_validators_require_convergence_and_frontiers(self) -> None:
        common_result = {
            "success": True,
            "core_mhz": 141.0,
            "vertices": 4,
            "initial_edges": 4,
            "logical_updates": 16,
            "physical_updates": 16,
            "update_edges": 16,
            "materialized_snapshot_edges": 4,
            "pagerank_damping": 0.85,
            "pagerank_epsilon": 1.0e-6,
            "iterations": 2,
            "converged": True,
            "residual_bound_passed": True,
            "frontier_in_sizes": [4, 1],
            "frontier_out_sizes": [1, 0],
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "correctness_mismatches": 0,
            "max_abs_error": 1.0e-7,
            "mathematical_max_abs_error": 2.0e-7,
            "residual_l1": 5.0e-7,
            "cycles": 400,
            "backend_requests": 40,
        }
        spine = {
            **common_result,
            "status": "PASS",
            "mode": "spine_residual_pagerank",
            "architecture_profile_id": "spine",
            "dynamic_update": True,
            "pipeline_order": (
                "zero_time_l0_preload_then_update_maintenance_then_compute"
            ),
            "maintenance_persisted_edges": 4,
            "residual_max_iterations": 256,
            "final_active": 0,
            "frontier_match": True,
            "memory_ledger_match": True,
            "ranks": [0.25] * 4,
            "residuals": [1.0e-7] * 4,
            "maintenance_cycles": 100,
            "maintenance_backend_requests": 10,
            "compute_backend_requests": 30,
            "dram_reads": 25,
            "dram_writes": 15,
        }
        spine = _with_traffic(
            spine, update_key="maintenance_backend_traffic"
        )
        spine_arguments = dict(
            expected_profile_id="spine",
            expected_core_mhz=141.0,
            damping=0.85,
            epsilon=1.0e-6,
            max_iterations=256,
        )
        self.assertEqual(
            validate_spine_residual_result(_run(), spine, **spine_arguments), []
        )
        grasu_result = {
            **common_result,
            "mode": "grasu_regraph_hls_weighted_residual_pagerank",
            "claim_class": (
                "hls_equivalent_proposed_execution_driven_simulation"
            ),
            "pipeline_order": "update_then_degree_barrier_then_pma_native_compute",
            "core_mhz": 200.0,
            "ranks_external": [0.25] * 4,
            "residuals_external": [1.0e-7] * 4,
            "compute_active_edges": 4,
            "expected_active_edges": 4,
            "gather_reset_cycles": 8,
            "gather_merge_cycles": 16,
            "gather_rows_emitted": 16,
            "update_cycles": 100,
            "compute_cycles": 300,
            "update_pma_reads": 16,
            "update_pma_writes": 16,
            "degree_update_reads": 16,
            "degree_update_writes": 16,
            "update_backend_requests": 10,
            "compute_backend_requests": 30,
            "expected_backend_requests": 40,
        }
        grasu_result = _with_traffic(
            grasu_result, update_key="update_backend_traffic"
        )
        child = {
            "status": "PASS",
            "profile_sha256": "profile",
            "result": grasu_result,
            "dram": {"reads": 25, "writes": 15},
        }
        grasu_arguments = dict(
            expected_profile_sha256="profile",
            expected_core_mhz=200.0,
            damping=0.85,
            epsilon=1.0e-6,
            max_iterations=256,
        )
        self.assertEqual(
            validate_grasu_residual_result(_run(), child, **grasu_arguments), []
        )
        grasu_result["frontier_out_sizes"] = [1, 1]
        self.assertIn(
            "frontier",
            validate_grasu_residual_result(_run(), child, **grasu_arguments),
        )

    def test_residual_pair_requires_rank_residual_and_frontier_match(self) -> None:
        common = {
            "run_id": "r",
            "dataset_id": "d",
            "scenario": "insert",
            "iterations": 2,
            "user_mutations": 8,
            "physical_records": 8,
            "e2e_ms": 2.0,
            "update_ms": 0.1,
            "compute_ms": 1.9,
            "backend_requests": 100,
            "backend_bytes": 3200,
            "compute_backend_requests": 90,
            "compute_backend_bytes": 2880,
            "ranks": (0.2, 0.8),
            "residuals": (1.0e-7, 2.0e-7),
            "frontier_in": (2, 1),
            "frontier_out": (1, 0),
        }
        grasu = {
            **common,
            "e2e_ms": 3.0,
            "compute_ms": 2.9,
            "backend_requests": 200,
            "backend_bytes": 6400,
            "compute_backend_requests": 190,
            "compute_backend_bytes": 6080,
            "ranks": (0.200001, 0.799999),
        }
        pair = residual_pair_row(common, grasu)
        self.assertEqual(pair["spine_speedup_over_grasu_e2e"], 1.5)
        self.assertTrue(pair["cross_system_frontiers_match"])
        broken = {**grasu, "frontier_out": (2, 0)}
        with self.assertRaisesRegex(ValueError, "residual mismatch"):
            residual_pair_row(common, broken)

    def test_residual_system_row_preserves_frontier_evidence(self) -> None:
        result = {
            "cycles": 400,
            "maintenance_cycles": 100,
            "maintenance_backend_requests": 10,
            "compute_backend_requests": 30,
            "backend_requests": 40,
            "core_mhz": 200.0,
            "iterations": 2,
            "residual_l1": 5.0e-7,
            "ranks": [0.25] * 4,
            "residuals": [1.0e-7] * 4,
            "frontier_in_sizes": [4, 1],
            "frontier_out_sizes": [1, 0],
            "correctness_mismatches": 0,
        }
        result = _with_traffic(
            result, update_key="maintenance_backend_traffic"
        )
        dram = {
            "reads": 25,
            "writes": 15,
            "activates": 5,
            "precharges": 4,
            "total_energy_pj": 100.0,
        }
        row = residual_system_row(
            _run(),
            system="spine",
            result=result,
            dram=dram,
            wall_seconds=1.0,
            profile_id="spine",
        )
        self.assertEqual(row["frontier_in"], (4, 1))
        self.assertEqual(row["compute_backend_bytes"], 960)
        self.assertEqual(row["compute_backend_nominal_64b_bytes"], 1920)


if __name__ == "__main__":
    unittest.main()
