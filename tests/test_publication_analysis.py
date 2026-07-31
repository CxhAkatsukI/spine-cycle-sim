from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.publication_analysis import (
    analyze_publication_case_results,
    capacity_exclusion_metadata,
    expected_execution_metadata,
    load_case_results_by_system,
    write_publication_analysis,
)


def case_result(system: str, cycles: int, *, execution_id: str | None = None) -> dict:
    execution_id = execution_id or f"execution_{system}"
    return {
        "schema_version": 1,
        "status": "pass",
        "case": {
            "execution_id": execution_id,
            "dataset_id": "graph",
            "system": system,
            "algorithm": "weighted_sssp",
            "scenario": "insert",
            "batch_size": 8,
            "graph": {
                "sha256": "1" * 64,
                "vertices": 4,
                "records": 6,
            },
            "update": {
                "sha256": "2" * 64,
                "user_mutations": 8,
                "physical_records": 8,
            },
            "source": 0,
            "algorithm_parameters": {"source_cohort": "default"},
        },
        "logical_views": ["main_e2e"],
        "row": {
            "run_id": execution_id,
            "system": system,
            "dataset_kind": "real",
            "role": "publication_large_graph",
            "cycles": cycles,
            "clock_mhz": 150.0,
            "backend_requests": 12,
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "dram_energy_pj": float(cycles),
            "host_wall_seconds": 1.0,
        },
        "final_state": {
            "field": "distances",
            "count": 4,
            "sha256": "3" * 64,
        },
        "scalar_metrics": {
            "update_cycles": 100,
            "maintenance_cycles": 25 if system == "spine" else 0,
        },
        "backend_arbitration": {"ledger_closed": True},
        "backend_traffic": {
            "combined": {
                "requests": 12,
                "bytes": 640,
                "first_requests": 0,
                "first_bytes": 0,
                "repeated_requests": 0,
                "repeated_bytes": 0,
                "contiguous_requests": 8,
                "contiguous_bytes": 512,
                "discontinuous_requests": 4,
                "discontinuous_bytes": 128,
            },
            "reads": {"bytes": 512},
            "writes": {"bytes": 128},
        },
        "measurement_backend_traffic": None,
        "dram": {"reads": 8, "writes": 4},
        "plugin_sha256": "a" * 64,
        "admission": {"child_returncode": 0, "parent_checks": {"all": True}},
    }


def attach_raw_result(result: dict, path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="ascii")
    result["raw_result_path"] = str(path)
    result["raw_result_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


class PublicationAnalysisTests(unittest.TestCase):
    def test_result_roots_can_be_filtered_by_architecture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for system in ("spine", "grasu_regraph_k4_shared"):
                result_dir = root / "runs" / system
                result_dir.mkdir(parents=True)
                (result_dir / "case_result.json").write_text(
                    json.dumps(case_result(system, 100), sort_keys=True) + "\n",
                    encoding="ascii",
                )

            selected = load_case_results_by_system([("spine", root)])
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]["case"]["system"], "spine")
            with self.assertRaisesRegex(ValueError, "unknown publication result system"):
                load_case_results_by_system([("unknown", root)])

    def test_complete_triplet_emits_two_correct_pairs(self) -> None:
        results = [
            case_result("spine", 100),
            case_result("grasu_regraph_k1", 400),
            case_result("grasu_regraph_k4_shared", 250),
        ]
        results[-1]["row"]["system"] = "grasu_regraph"
        analysis = analyze_publication_case_results(
            results,
            expected_execution_ids={row["case"]["execution_id"] for row in results},
            require_complete=True,
        )
        self.assertEqual(analysis["status"], "PASS")
        self.assertEqual(analysis["complete_triplets"], 1)
        self.assertEqual(len(analysis["pair_rows"]), 2)
        self.assertTrue(
            analysis["evidence_audit"]["all_observed_executions_audited"]
        )
        self.assertEqual(
            analysis["evidence_audit"]["dram_request_ledgers_closed"], 3
        )
        speedups = {
            row["competitor"]: row["spine_speedup"]
            for row in analysis["pair_rows"]
        }
        self.assertEqual(speedups["grasu_regraph_k1"], 4.0)
        self.assertEqual(speedups["grasu_regraph_k4_shared"], 2.5)
        k4 = next(
            row
            for row in analysis["pair_rows"]
            if row["competitor"] == "grasu_regraph_k4_shared"
        )
        self.assertEqual(k4["spine_host_wall_seconds"], 1.0)
        self.assertEqual(k4["competitor_host_wall_seconds"], 1.0)

    def test_declared_pair_is_complete_without_diagnostic_k1(self) -> None:
        results = [
            case_result("spine", 100),
            case_result("grasu_regraph_k4_shared", 250),
        ]
        analysis = analyze_publication_case_results(
            results,
            expected_execution_ids={row["case"]["execution_id"] for row in results},
            required_systems=("spine", "grasu_regraph_k4_shared"),
            require_complete=True,
        )
        self.assertEqual(analysis["status"], "PASS")
        self.assertEqual(
            analysis["required_systems"],
            ["spine", "grasu_regraph_k4_shared"],
        )
        self.assertTrue(analysis["correctness_groups"][0]["complete_triplet"])
        self.assertEqual(analysis["correctness_groups"][0]["missing_systems"], "")
        self.assertEqual(len(analysis["pair_rows"]), 1)

    def test_required_systems_reject_duplicates(self) -> None:
        with self.assertRaisesRegex(ValueError, "required systems"):
            analyze_publication_case_results(
                [case_result("spine", 100)],
                required_systems=("spine", "spine"),
            )

    def test_cross_system_final_state_mismatch_is_recorded_and_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spine = case_result("spine", 100)
            competitor = case_result("grasu_regraph_k1", 400)
            competitor["final_state"]["sha256"] = "4" * 64
            attach_raw_result(
                spine,
                Path(temporary) / "spine.json",
                {"final_values": [0, 1, 2, 3]},
            )
            attach_raw_result(
                competitor,
                Path(temporary) / "competitor.json",
                {"distances_external": [0, 1, 9, 3]},
            )
            analysis = analyze_publication_case_results([spine, competitor])
            self.assertEqual(analysis["status"], "FAIL")
            self.assertEqual(analysis["failed_correctness_groups"], 1)
            self.assertFalse(
                analysis["correctness_groups"][0]["final_state_match"]
            )
            self.assertEqual(analysis["pair_rows"], [])

    def test_float_external_vectors_use_explicit_tolerance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spine = case_result("spine", 100)
            competitor = case_result("grasu_regraph_k1", 400)
            for result in (spine, competitor):
                result["case"]["algorithm"] = "full_pagerank"
                result["case"]["algorithm_parameters"] = {
                    "iterations": 3,
                    "damping": 0.85,
                }
            competitor["final_state"]["sha256"] = "4" * 64
            attach_raw_result(
                spine,
                Path(temporary) / "spine.json",
                {"ranks": [0.1, 0.2, 0.3, 0.4]},
            )
            attach_raw_result(
                competitor,
                Path(temporary) / "competitor.json",
                {
                    "ranks": [0.4, 0.3, 0.2, 0.1],
                    "ranks_external": [0.1, 0.2 + 1.2e-6, 0.3, 0.4],
                },
            )
            analysis = analyze_publication_case_results([spine, competitor])
            group = analysis["correctness_groups"][0]
            self.assertTrue(group["final_state_match"])
            self.assertFalse(group["final_state_exact_match"])
            self.assertAlmostEqual(group["cross_system_max_abs_error"], 1.2e-6)
            self.assertEqual(group["cross_system_tolerance"], 1.0e-5)

    def test_float_external_vectors_over_tolerance_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spine = case_result("spine", 100)
            competitor = case_result("grasu_regraph_k4_shared", 250)
            for result in (spine, competitor):
                result["case"]["algorithm"] = "full_pagerank"
                result["case"]["algorithm_parameters"] = {
                    "iterations": 3,
                    "damping": 0.85,
                }
            competitor["final_state"]["sha256"] = "4" * 64
            attach_raw_result(
                spine,
                Path(temporary) / "spine.json",
                {"ranks_external": [0.1, 0.2, 0.3, 0.4]},
            )
            attach_raw_result(
                competitor,
                Path(temporary) / "competitor.json",
                {"ranks_external": [0.1, 0.2 + 1.1e-5, 0.3, 0.4]},
            )
            analysis = analyze_publication_case_results([spine, competitor])
            self.assertEqual(analysis["status"], "FAIL")
            self.assertEqual(analysis["failed_correctness_groups"], 1)
            self.assertEqual(analysis["pair_rows"], [])

    def test_duplicate_execution_must_keep_scientific_result(self) -> None:
        first = case_result("spine", 100, execution_id="same")
        duplicate = deepcopy(first)
        duplicate["row"]["host_wall_seconds"] = 2.0
        duplicate["scalar_metrics"]["sst_host_wall_seconds"] = 3.0
        analysis = analyze_publication_case_results([first, duplicate])
        self.assertEqual(analysis["observed_executions"], 1)
        self.assertEqual(analysis["duplicate_executions"], 1)
        self.assertEqual(analysis["system_rows"][0]["host_wall_seconds"], 1.0)
        changed = deepcopy(first)
        changed["row"]["cycles"] = 101
        with self.assertRaisesRegex(ValueError, "changed scientific result"):
            analyze_publication_case_results([first, changed])

    def test_behavior_transition_invalidates_affected_old_spine_result(self) -> None:
        old = case_result("spine", 100, execution_id="transition")
        old["scalar_metrics"]["resident_hot_edges"] = 7
        policy = {
            "classification": "hls_behavior_correction",
            "scope_system": "spine",
            "affected_metric": "resident_hot_edges",
            "affected_when_greater_than": 0,
            "requires_identical_case": True,
            "requires_identical_final_state": True,
            "superseded_plugin_sha256": ["a" * 64],
            "superseding_plugin_sha256": "b" * 64,
        }
        analysis = analyze_publication_case_results(
            [old],
            expected_execution_ids={"transition"},
            result_supersedence_policy=policy,
        )
        self.assertEqual(analysis["observed_executions"], 0)
        self.assertEqual(
            analysis["transition_invalidated_execution_ids"], ["transition"]
        )
        self.assertEqual(
            analysis["execution_coverage_rows"][0]["coverage_status"],
            "invalidated_by_behavior_transition",
        )

    def test_behavior_transition_explicit_successor_replaces_old_result(self) -> None:
        old = case_result("spine", 100, execution_id="transition")
        old["scalar_metrics"]["resident_hot_edges"] = 7
        new = deepcopy(old)
        new["plugin_sha256"] = "b" * 64
        new["row"]["cycles"] = 125
        new["scalar_metrics"]["update_cycles"] = 125
        policy = {
            "classification": "hls_behavior_correction",
            "scope_system": "spine",
            "affected_metric": "resident_hot_edges",
            "affected_when_greater_than": 0,
            "requires_identical_case": True,
            "requires_identical_final_state": True,
            "superseded_plugin_sha256": ["a" * 64],
            "superseding_plugin_sha256": "b" * 64,
        }
        analysis = analyze_publication_case_results(
            [old, new], result_supersedence_policy=policy
        )
        self.assertEqual(analysis["observed_executions"], 1)
        self.assertEqual(analysis["system_rows"][0]["cycles"], 125)
        self.assertEqual(len(analysis["superseded_result_rows"]), 1)
        self.assertEqual(
            analysis["superseded_result_rows"][0]["old_cycles"], 100
        )

        changed_state = deepcopy(new)
        changed_state["final_state"]["sha256"] = "4" * 64
        with self.assertRaisesRegex(ValueError, "changed final state"):
            analyze_publication_case_results(
                [old, changed_state], result_supersedence_policy=policy
            )

    def test_device_active_transition_replaces_old_timing_result(self) -> None:
        old = case_result("spine", 100, execution_id="device_active")
        old["row"]["algorithm"] = "weighted_dynamic_sssp"
        old["scalar_metrics"]["resident_hot_edges"] = 0
        new = deepcopy(old)
        new["plugin_sha256"] = "b" * 64
        new["row"]["cycles"] = 140
        policy = {
            "classification": "device_active_timing_correction",
            "scope_system": "spine",
            "affected_algorithms": [
                "connected_components",
                "thresholded_residual_pagerank",
                "weighted_sssp",
                "weighted_dynamic_sssp",
            ],
            "requires_identical_case": True,
            "requires_identical_final_state": True,
            "superseded_plugin_sha256": ["a" * 64],
            "superseding_plugin_sha256": "b" * 64,
        }
        analysis = analyze_publication_case_results(
            [old, new], result_supersedence_policy=policy
        )
        self.assertEqual(analysis["observed_executions"], 1)
        self.assertEqual(analysis["system_rows"][0]["cycles"], 140)
        self.assertEqual(
            analysis["superseded_result_rows"][0]["affected_metric"],
            "algorithm_timing_semantics",
        )
        self.assertEqual(
            analysis["superseded_result_rows"][0]["affected_metric_value"],
            "weighted_dynamic_sssp",
        )

        unaffected = deepcopy(old)
        unaffected["row"]["algorithm"] = "full_pagerank"
        analysis = analyze_publication_case_results(
            [unaffected], result_supersedence_policy=policy
        )
        self.assertEqual(analysis["observed_executions"], 1)
        self.assertEqual(analysis["system_rows"][0]["cycles"], 100)

    def test_device_residual_transition_only_replaces_residual_result(self) -> None:
        old = case_result("spine", 100, execution_id="device_residual")
        old["row"]["algorithm"] = "thresholded_residual_pagerank"
        new = deepcopy(old)
        new["plugin_sha256"] = "b" * 64
        new["row"]["cycles"] = 115
        policy = {
            "classification": "device_residual_correction_timing",
            "scope_system": "spine",
            "affected_algorithms": ["thresholded_residual_pagerank"],
            "requires_identical_case": True,
            "requires_identical_final_state": True,
            "superseded_plugin_sha256": ["a" * 64],
            "superseding_plugin_sha256": "b" * 64,
        }
        analysis = analyze_publication_case_results(
            [old, new], result_supersedence_policy=policy
        )
        self.assertEqual(analysis["observed_executions"], 1)
        self.assertEqual(analysis["system_rows"][0]["cycles"], 115)

        unaffected = deepcopy(old)
        unaffected["row"]["algorithm"] = "connected_components"
        analysis = analyze_publication_case_results(
            [unaffected], result_supersedence_policy=policy
        )
        self.assertEqual(analysis["observed_executions"], 1)
        self.assertEqual(analysis["system_rows"][0]["cycles"], 100)

    def test_ordered_transition_chain_selects_algorithm_specific_successors(self) -> None:
        old_cc = case_result("spine", 100, execution_id="cc")
        old_cc["row"]["algorithm"] = "connected_components"
        device_cc = deepcopy(old_cc)
        device_cc["plugin_sha256"] = "b" * 64
        device_cc["row"]["cycles"] = 110

        old_residual = case_result("spine", 200, execution_id="residual")
        old_residual["row"]["algorithm"] = "thresholded_residual_pagerank"
        device_residual = deepcopy(old_residual)
        device_residual["plugin_sha256"] = "b" * 64
        device_residual["row"]["cycles"] = 220
        corrected_residual = deepcopy(old_residual)
        corrected_residual["plugin_sha256"] = "c" * 64
        corrected_residual["row"]["cycles"] = 240

        device_active = {
            "classification": "device_active_timing_correction",
            "scope_system": "spine",
            "affected_algorithms": [
                "connected_components",
                "thresholded_residual_pagerank",
            ],
            "requires_identical_case": True,
            "requires_identical_final_state": True,
            "superseded_plugin_sha256": ["a" * 64],
            "superseding_plugin_sha256": "b" * 64,
        }
        device_correction = {
            "classification": "device_residual_correction_timing",
            "scope_system": "spine",
            "affected_algorithms": ["thresholded_residual_pagerank"],
            "requires_identical_case": True,
            "requires_identical_final_state": True,
            "superseded_plugin_sha256": ["a" * 64, "b" * 64],
            "superseding_plugin_sha256": "c" * 64,
        }
        analysis = analyze_publication_case_results(
            [
                old_cc,
                device_cc,
                old_residual,
                device_residual,
                corrected_residual,
            ],
            result_supersedence_policy=[device_active, device_correction],
        )
        cycles = {
            row["execution_id"]: row["cycles"]
            for row in analysis["system_rows"]
        }
        self.assertEqual(cycles, {"cc": 110, "residual": 240})
        transitions = {
            (row["execution_id"], row["old_cycles"]): row[
                "transition_classification"
            ]
            for row in analysis["superseded_result_rows"]
        }
        self.assertEqual(
            transitions,
            {
                ("cc", 100): "device_active_timing_correction",
                ("residual", 200): "device_residual_correction_timing",
                ("residual", 220): "device_residual_correction_timing",
            },
        )

    def test_incomplete_expected_set_is_partial_or_fail_closed(self) -> None:
        result = case_result("spine", 100)
        analysis = analyze_publication_case_results(
            [result], expected_execution_ids={result["case"]["execution_id"], "missing"}
        )
        self.assertEqual(analysis["status"], "PARTIAL")
        self.assertEqual(analysis["missing_execution_ids"], ["missing"])
        coverage = {
            row["execution_id"]: row["coverage_status"]
            for row in analysis["execution_coverage_rows"]
        }
        self.assertEqual(coverage["execution_spine"], "observed_pass")
        self.assertEqual(coverage["missing"], "missing")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            analyze_publication_case_results(
                [result],
                expected_execution_ids={result["case"]["execution_id"], "missing"},
                require_complete=True,
            )

    def test_normalization_uses_executed_traffic_and_update_cycles(self) -> None:
        result = case_result("spine", 300)
        result["scalar_metrics"] = {
            "update_cycles": 250,
            "maintenance_cycles": 75,
        }
        analysis = analyze_publication_case_results([result])
        row = analysis["system_rows"][0]
        self.assertEqual(row["update_cycles"], 250)
        self.assertEqual(row["structure_update_cycles"], 75)
        self.assertEqual(row["structure_update_counter"], "maintenance_cycles")
        self.assertAlmostEqual(row["sequential_request_fraction"], 2.0 / 3.0)
        self.assertEqual(row["read_bytes"] + row["write_bytes"], 640)

    def test_pair_separates_structure_update_from_dynamic_service(self) -> None:
        spine = case_result("spine", 300)
        spine["scalar_metrics"].update(
            {"update_cycles": 250, "maintenance_cycles": 75}
        )
        competitor = case_result("grasu_regraph_k4_shared", 400)
        competitor["scalar_metrics"]["update_cycles"] = 20
        analysis = analyze_publication_case_results([spine, competitor])
        pair = analysis["pair_rows"][0]
        self.assertEqual(pair["spine_update_cycles"], 250)
        self.assertEqual(pair["spine_structure_update_cycles"], 75)
        self.assertEqual(pair["competitor_structure_update_cycles"], 20)
        self.assertAlmostEqual(pair["spine_structure_update_speedup"], 20 / 75)

    def test_normalization_separates_complete_and_measurement_traffic(self) -> None:
        result = case_result("spine", 300)
        result["measurement_backend_traffic"] = deepcopy(
            result["backend_traffic"]
        )
        measured = result["measurement_backend_traffic"]
        measured["combined"].update(
            {
                "requests": 3,
                "bytes": 192,
                "first_requests": 1,
                "first_bytes": 64,
                "contiguous_requests": 1,
                "contiguous_bytes": 64,
                "discontinuous_requests": 1,
                "discontinuous_bytes": 64,
            }
        )
        measured["reads"]["bytes"] = 128
        measured["writes"]["bytes"] = 64
        analysis = analyze_publication_case_results([result])
        row = analysis["system_rows"][0]
        self.assertEqual(row["backend_requests"], 3)
        self.assertEqual(row["read_bytes"] + row["write_bytes"], 192)

    def test_analysis_rejects_open_memory_ledgers(self) -> None:
        result = case_result("spine", 300)
        result["backend_traffic"]["combined"]["discontinuous_requests"] = 3
        with self.assertRaisesRegex(ValueError, "traffic ledger does not close"):
            analyze_publication_case_results([result])

        result = case_result("spine", 300)
        result["dram"]["writes"] = 3
        with self.assertRaisesRegex(ValueError, "DRAM request ledger does not close"):
            analyze_publication_case_results([result])

    def test_spine_dynamic_sssp_uses_e2e_convergence_window(self) -> None:
        result = case_result("spine", 1_000)
        result["scalar_metrics"] = {
            "cold_cycles": 900,
            "update_cycles": 100,
            "algorithm_warm_start": False,
        }
        analysis = analyze_publication_case_results([result])
        row = analysis["system_rows"][0]
        self.assertEqual(row["cycles"], 1_000)
        self.assertEqual(row["raw_cycles"], 1_000)
        self.assertEqual(row["bootstrap_cycles"], 900)
        self.assertEqual(row["measurement_window"], "dynamic_e2e_to_convergence")
        self.assertFalse(row["algorithm_warm_start"])

    def test_component_activity_preserves_lists_and_claim_boundary(self) -> None:
        result = case_result("spine", 300)
        result["scalar_metrics"] = {
            "maintenance_cycles": 30,
            "maintenance_edge_visits": 16,
            "maintenance_backend_requests": 5,
            "reader_active_cycles_per_round": [10, 20],
            "reader_memory_requests_issued_per_round": [2, 3],
            "reader_memory_window_stall_cycles_per_round": [4, 5],
            "compute_active_cycles_per_round": [40, 50],
            "compute_tiny_bram_read_requests_per_round": [7, 8],
            "compute_tiny_bram_write_requests_per_round": [3, 4],
            "backend_requests": 12,
            "hbm_queue_stalls": 9,
        }
        result["dram"] = {"reads": 8, "writes": 4}
        analysis = analyze_publication_case_results([result])
        rows = {
            row["component"]: row
            for row in analysis["component_activity_rows"]
        }
        self.assertEqual(rows["reader"]["component_cycles"], 30)
        self.assertEqual(rows["reader"]["backend_requests"], 5)
        self.assertEqual(rows["reader"]["stall_cycles"], 9)
        self.assertEqual(rows["onchip_state_arrays"]["read_events"], 15)
        self.assertEqual(rows["onchip_state_arrays"]["write_events"], 7)
        self.assertEqual(rows["hbm_frontend"]["read_events"], 8)
        self.assertEqual(rows["hbm_frontend"]["write_events"], 4)
        self.assertEqual(
            rows["hbm_frontend"]["claim_scope"],
            "workload_specific_activity_not_total_energy",
        )

    def test_device_residual_correction_is_a_disjoint_component(self) -> None:
        result = case_result("spine", 300)
        result["row"]["algorithm"] = "thresholded_residual_pagerank"
        result["scalar_metrics"] = {
            "maintenance_cycles": 30,
            "reader_cycles": 20,
            "residual_correction_device_timed": True,
            "residual_correction_cycles": 40,
            "residual_correction_memory_requests": 18,
            "residual_correction_physical_edge_records": 5,
            "residual_correction_rank_read_bytes": 8,
            "residual_correction_degree_read_bytes": 8,
            "residual_correction_graph_read_bytes": 40,
            "residual_correction_residual_read_bytes": 12,
            "residual_correction_degree_write_bytes": 8,
            "residual_correction_residual_write_bytes": 12,
            "residual_correction_active_write_bytes": 4,
        }
        analysis = analyze_publication_case_results([result])
        system = analysis["system_rows"][0]
        rows = {
            row["component"]: row
            for row in analysis["component_activity_rows"]
        }
        self.assertEqual(system["residual_correction_cycles"], 40)
        self.assertEqual(system["residual_correction_read_bytes"], 68)
        self.assertEqual(system["residual_correction_write_bytes"], 24)
        self.assertEqual(rows["residual_correction"]["component_cycles"], 40)
        self.assertEqual(rows["residual_correction"]["work_items"], 5)
        self.assertEqual(rows["residual_correction"]["read_events"], 12)
        self.assertEqual(rows["residual_correction"]["write_events"], 6)
        self.assertEqual(rows["residual_correction"]["backend_requests"], 18)
        self.assertEqual(rows["compute"]["component_cycles"], 210)

    def test_writer_emits_component_activity_csv(self) -> None:
        analysis = analyze_publication_case_results([case_result("spine", 100)])
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            write_publication_analysis(output, analysis)
            activity = (output / "component_activity_rows.csv").read_text()
            coverage = (output / "execution_coverage_rows.csv").read_text()
            exclusions = (output / "capacity_exclusion_rows.csv").read_text()
        self.assertIn("component_cycles", activity)
        self.assertIn("hbm_frontend", activity)
        self.assertIn("coverage_status", coverage)
        self.assertIn("observed_pass", coverage)
        self.assertEqual(exclusions, "")

    def test_writer_accepts_heterogeneous_capacity_metadata(self) -> None:
        analysis = analyze_publication_case_results(
            [case_result("spine", 100)],
            capacity_exclusion_records=[
                {
                    "execution_id": "row-bound",
                    "reason": "row_storage_bound",
                    "row_storage_lower_bound_bytes": 20,
                },
                {
                    "execution_id": "vertex-bound",
                    "reason": "vertex_capacity_bound",
                    "spine_max_vertices": 1 << 24,
                },
            ],
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            write_publication_analysis(output, analysis)
            exclusions = (output / "capacity_exclusion_rows.csv").read_text()
        self.assertIn("row_storage_lower_bound_bytes", exclusions)
        self.assertIn("spine_max_vertices", exclusions)

    def test_expected_execution_metadata_is_human_readable_and_merged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifests = []
            for campaign_id, view in (("campaign_a", "main_e2e"), ("campaign_b", "memory")):
                path = root / f"{campaign_id}.json"
                path.write_text(
                    json.dumps(
                        {
                            "campaign_id": campaign_id,
                            "execution_views": {"abc123": [view]},
                            "jobs": [
                                {
                                    "job_id": "run.graph.weighted_sssp.insert.u8.spine.abc123",
                                    "dataset_id": "graph",
                                    "algorithm": "weighted_sssp",
                                    "system": "spine",
                                    "tier": view,
                                    "estimated_rss_gib": 2.5,
                                    "command": [
                                        "python3",
                                        "runner.py",
                                        "--scenario",
                                        "insert",
                                        "--batch-size",
                                        "8",
                                    ],
                                }
                            ],
                        }
                    )
                    + "\n",
                    encoding="ascii",
                )
                manifests.append(path)
            metadata = expected_execution_metadata(manifests)
        self.assertEqual(metadata["abc123"]["dataset_id"], "graph")
        self.assertEqual(metadata["abc123"]["batch_size"], 8)
        self.assertEqual(metadata["abc123"]["logical_views"], "main_e2e+memory")
        self.assertEqual(
            metadata["abc123"]["campaign_ids"], "campaign_a+campaign_b"
        )

    def test_capacity_exclusion_is_audited_but_not_expected_to_run(self) -> None:
        result = case_result("spine", 100)
        analysis = analyze_publication_case_results(
            [result],
            expected_execution_ids={"execution_spine"},
            capacity_exclusion_records=[
                {
                    "execution_id": "capacity_case",
                    "dataset_id": "large",
                    "algorithm": "weighted_sssp",
                    "scenario": "insert",
                    "batch_size": 8,
                    "system": "grasu_regraph_k4_shared",
                    "tier": "main_e2e",
                    "reason": "grasu_hbm_row_storage_lower_bound",
                }
            ],
        )
        self.assertEqual(analysis["expected_executions"], 1)
        self.assertEqual(analysis["capacity_excluded_executions"], 1)
        self.assertEqual(analysis["contract_executions"], 2)
        coverage = {
            row["execution_id"]: row["coverage_status"]
            for row in analysis["execution_coverage_rows"]
        }
        self.assertEqual(coverage["capacity_case"], "capacity_excluded")

    def test_capacity_exclusion_metadata_preserves_physical_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(
                json.dumps(
                    {
                        "campaign_id": "campaign",
                        "capacity_exclusions": [
                            {
                                "execution_id": "excluded",
                                "dataset_id": "large",
                                "algorithm": "weighted_sssp",
                                "system": "grasu_regraph_k4_shared",
                                "scenario": "insert",
                                "batch_size": 8,
                                "tier": "main_e2e",
                                "reason": "grasu_hbm_row_storage_lower_bound",
                                "row_storage_lower_bound_bytes": 20,
                                "hbm_capacity_bytes": 10,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="ascii",
            )
            rows = capacity_exclusion_metadata([path])
        self.assertEqual(rows[0]["execution_id"], "excluded")
        self.assertEqual(rows[0]["campaign_ids"], "campaign")
        self.assertGreater(
            rows[0]["row_storage_lower_bound_bytes"],
            rows[0]["hbm_capacity_bytes"],
        )


if __name__ == "__main__":
    unittest.main()
