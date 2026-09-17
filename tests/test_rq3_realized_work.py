from __future__ import annotations

import hashlib
import gzip
import json
import tempfile
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.rq3 import (
    analyze_rq3_results,
    fit_e2e_cost_model,
    linear_fit,
    write_rq3_analysis,
)


def result(execution_id: str = "rq3") -> dict:
    return {
        "status": "pass",
        "case": {
            "execution_id": execution_id,
            "dataset_id": "trace",
            "system": "spine",
            "algorithm": "weighted_sssp",
            "scenario": "insert",
            "batch_size": 8,
            "update": {"user_mutations": 8, "physical_records": 8},
        },
        "row": {
            "cycles": 100,
            "dataset_kind": "real",
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
        },
        "scalar_metrics": {
            "update_cycles": 100,
            "maintenance_start_cycle": 0,
            "maintenance_end_cycle": 20,
            "maintenance_cycles": 20,
            "maintenance_stage_xfer_cycles": 2,
            "maintenance_stage_reduce_cycles": 3,
            "maintenance_stage_carry_cycles": 0,
            "maintenance_stage_directory_cycles": 5,
            "maintenance_stage_seed_cycles": 4,
            "maintenance_stage_switch_cycles": 6,
            "maintenance_stage_ledger_closed": True,
            "maintenance_target_level": 0,
            "maintenance_persisted_edges": 8,
            "maintenance_dirty_unique_sources": 2,
            "maintenance_target_selector_metadata_reads": 32,
            "maintenance_target_selector_cycles": 10,
            "reader_start_cycles_per_round": [20, 80],
            "reader_end_cycles_per_round": [60, 90],
            "compute_start_cycles_per_round": [40, 88],
            "compute_end_cycles_per_round": [75, 95],
            "round_start_cycles": [0, 80],
            "round_end_cycles": [75, 100],
            "reader_active_cycles_per_round": [40, 10],
            "compute_active_cycles_per_round": [35, 7],
            "reader_range_construction_payloads_per_round": [16, 0],
            "reader_range_replay_payloads_per_round": [16, 0],
            "processed_edges_per_round": [16, 0],
            "reader_source_requests_per_round": [2, 1],
            "frontier_out_sizes": [1, 0],
        },
    }


class Rq3RealizedWorkTests(unittest.TestCase):
    def test_zero_round_correction_requires_explicit_no_work_evidence(self) -> None:
        residual = result("zero-round-correction")
        residual["case"]["algorithm"] = "thresholded_residual_pagerank"
        metrics = residual["scalar_metrics"]
        for key in (
            "success", "converged", "residual_correction_device_timed",
            "residual_correction_request_ledger_closed", "active_edge_execution_ledger_match",
            "owner_scheduler_enabled", "owner_ledger_closed", "owner_quiescent",
        ):
            metrics[key] = True
        for key in (
            "correctness_mismatches", "architecture_correctness_mismatches",
            "mathematical_correctness_mismatches", "iterations", "initial_active_vertices",
            "final_active", "reader_edges_total", "compute_edges_total", "expected_active_edges",
            "owner_dispatches", "owner_completions", "owner_work_credits_created",
            "owner_work_credits_retired",
        ):
            metrics[key] = 0
        for key in (
            "iteration_cycles", "round_start_cycles", "round_end_cycles",
            "reader_start_cycles_per_round", "reader_end_cycles_per_round",
            "compute_start_cycles_per_round", "compute_end_cycles_per_round",
        ):
            metrics[key] = []
        metrics["residual_correction_cycles"] = 70
        row = analyze_rq3_results([residual])["latency_rows"][0]
        self.assertTrue(row["ten_stage_ledger_closed"])
        self.assertEqual(row["t_resolve_cycles"], 0)
        self.assertEqual(row["t_app_cycles"], 0)
        self.assertEqual(row["t_seed_cycles"], 74)
        self.assertEqual(row["t_drain_cycles"], 10)
        self.assertEqual(row["integrated_resolve_app_cycles"], 0)
        for key, bad in (
            ("iterations", 1), ("compute_edges_total", 1), ("owner_dispatches", 1),
            ("residual_correction_request_ledger_closed", False),
            ("reader_end_cycles_per_round", None),
        ):
            with self.subTest(key=key):
                previous = metrics.pop(key)
                if bad is not None:
                    metrics[key] = bad
                rejected = analyze_rq3_results([residual])["latency_rows"][0]
                self.assertFalse(rejected["ten_stage_supported"])
                metrics[key] = previous

    def test_overlap_aware_ledger_closes_exactly(self) -> None:
        analysis = analyze_rq3_results([result()])
        row = analysis["latency_rows"][0]
        self.assertTrue(row["ledger_closed"])
        self.assertEqual(row["total_cycles"], 100)
        self.assertEqual(row["maintenance_cycles"], 20)
        self.assertEqual(row["resolve_app_overlap_cycles"], 22)
        self.assertEqual(row["sync_cycles"], 5)
        self.assertEqual(
            row["total_cycles"],
            sum(
                row[key]
                for key in (
                    "maintenance_cycles",
                    "resolve_only_cycles",
                    "app_only_cycles",
                    "resolve_app_overlap_cycles",
                    "integrated_resolve_app_cycles",
                    "sync_cycles",
                    "other_cycles",
                )
            ),
        )

    def test_direct_ten_stage_ledger_closes_exactly(self) -> None:
        row = analyze_rq3_results([result()])["latency_rows"][0]
        self.assertTrue(row["ten_stage_supported"])
        self.assertTrue(row["ten_stage_ledger_closed"])
        self.assertEqual(row["t_xfer_cycles"], 2)
        self.assertEqual(row["t_reduce_cycles"], 3)
        self.assertEqual(row["t_resolve_cycles"], 28)
        self.assertEqual(row["t_app_cycles"], 42)
        self.assertEqual(
            row["total_cycles"],
            sum(value for key, value in row.items() if key.startswith("t_") and key.endswith("_cycles")),
        )

    def test_realized_work_uses_direct_execution_counters(self) -> None:
        row = analyze_rq3_results([result()])["work_rows"][0]
        self.assertEqual(row["w_sort_records"], 8)
        self.assertEqual(row["directory_requests"], 32)
        self.assertEqual(row["m_phys_records"], 16)
        self.assertEqual(row["m_seed_records"], 2)
        self.assertEqual(row["source_services"], 3)
        self.assertEqual(row["reactivations"], 1)
        self.assertEqual(row["case_class"], "shallow_insertion")

    def test_current_sssp_window_uses_full_dynamic_e2e_cycles(self) -> None:
        current = result("current-window")
        current["row"]["cycles"] = 150
        current["row"]["measurement_window"] = "dynamic_e2e_to_convergence"
        current["scalar_metrics"]["update_cycles"] = 20
        row = analyze_rq3_results([current])["latency_rows"][0]
        self.assertEqual(row["total_cycles"], 150)
        self.assertTrue(row["ledger_closed"])

    def test_device_residual_correction_is_timed_inside_seed_stage(self) -> None:
        residual = result("device-correction")
        residual["case"]["algorithm"] = "thresholded_residual_pagerank"
        residual["row"]["cycles"] = 110
        metrics = residual["scalar_metrics"]
        metrics.update(
            {
                "residual_correction_device_timed": True,
                "residual_correction_cycles": 10,
                "residual_correction_physical_edge_records": 12,
                "residual_correction_seeded_vertices": 3,
                "residual_correction_memory_requests": 24,
                "reader_start_cycles_per_round": [30, 90],
                "reader_end_cycles_per_round": [70, 100],
                "compute_start_cycles_per_round": [50, 98],
                "compute_end_cycles_per_round": [85, 105],
                "round_start_cycles": [0, 90],
                "round_end_cycles": [85, 110],
            }
        )
        analysis = analyze_rq3_results([residual])
        work = analysis["work_rows"][0]
        latency = analysis["latency_rows"][0]
        self.assertEqual(work["m_seed_records"], 15)
        self.assertEqual(work["residual_correction_memory_requests"], 24)
        self.assertEqual(latency["residual_correction_cycles"], 10)
        self.assertEqual(latency["t_seed_cycles"], 14)
        self.assertTrue(latency["residual_correction_seed_timed"])
        self.assertTrue(latency["ten_stage_ledger_closed"])
        self.assertEqual(
            latency["total_cycles"],
            sum(
                value
                for key, value in latency.items()
                if key.startswith("t_") and key.endswith("_cycles")
            ),
        )

    def test_carry_work_counts_payload_merge_and_rewrite(self) -> None:
        carry = result("carry")
        carry["scalar_metrics"].update(
            {
                "maintenance_target_level": 3,
                "maintenance_carry_payload_reads": 28,
                "maintenance_carry_new_batch_reads": 4,
                "maintenance_carry_merge_inputs": 32,
                "maintenance_carry_outputs": 32,
                "maintenance_carry_cursor_bits_inspected": 768,
            }
        )
        row = analyze_rq3_results([carry])["work_rows"][0]
        self.assertEqual(row["w_carry_records"], 92)
        self.assertEqual(row["w_carry_cursor_bits"], 768)
        self.assertEqual(row["case_class"], "deep_carry")

    def test_missing_persisted_counter_is_not_zero_net(self) -> None:
        cc = result("cc")
        cc["case"]["algorithm"] = "connected_components"
        del cc["scalar_metrics"]["maintenance_persisted_edges"]
        row = analyze_rq3_results([cc])["work_rows"][0]
        self.assertEqual(row["case_class"], "shallow_insertion")

    def test_zero_net_requires_explicit_execution_evidence(self) -> None:
        zero = result("zero")
        zero["scalar_metrics"]["maintenance_persisted_edges"] = 0
        zero["scalar_metrics"]["update_mode"] = "zero_net_no_repair"
        analysis = analyze_rq3_results([zero])
        self.assertEqual(analysis["work_rows"][0]["case_class"], "zero_net")
        self.assertEqual(analysis["coverage_rows"][0]["status"], "ready")

    def test_zero_net_ten_stage_ledger_accepts_no_component_launch(self) -> None:
        zero = result("zero-no-launch")
        zero["scalar_metrics"]["maintenance_persisted_edges"] = 0
        for key in (
            "reader_start_cycles_per_round",
            "reader_end_cycles_per_round",
            "compute_start_cycles_per_round",
            "compute_end_cycles_per_round",
            "round_start_cycles",
            "round_end_cycles",
        ):
            zero["scalar_metrics"][key] = []
        row = analyze_rq3_results([zero])["latency_rows"][0]
        self.assertTrue(row["ten_stage_supported"])
        self.assertTrue(row["ten_stage_ledger_closed"])
        self.assertEqual(row["t_drain_cycles"], 80)

    def test_full_pagerank_is_not_residual_correction(self) -> None:
        full = result("full")
        full["case"]["algorithm"] = "full_pagerank"
        row = analyze_rq3_results([full])["work_rows"][0]
        self.assertEqual(row["case_class"], "full_pagerank")

    def test_representative_coverage_rejects_zero_work_residual(self) -> None:
        residual = result("residual")
        residual["case"]["algorithm"] = "thresholded_residual_pagerank"
        residual["scalar_metrics"]["processed_edges_per_round"] = [0]
        residual["scalar_metrics"]["reader_range_construction_payloads_per_round"] = [0]
        residual["scalar_metrics"]["reader_range_replay_payloads_per_round"] = [0]
        residual["scalar_metrics"]["reader_fallback_replay_edges_per_round"] = [0]
        residual["scalar_metrics"].pop("reader_edges_total", None)
        residual["scalar_metrics"].pop("compute_edges_total", None)
        coverage = {
            row["case_class"]: row
            for row in analyze_rq3_results([residual])["coverage_rows"]
        }
        self.assertEqual(coverage["pagerank_correction"]["status"], "missing")

    def test_legacy_cold_timestamps_are_rebased_to_the_update_window(self) -> None:
        cold = result("cold")
        metrics = cold["scalar_metrics"]
        origin = 1_000
        metrics["cold_cycles"] = origin
        for key in (
            "maintenance_start_cycle",
            "maintenance_end_cycle",
        ):
            metrics[key] += origin
        for key in (
            "reader_start_cycles_per_round",
            "reader_end_cycles_per_round",
            "compute_start_cycles_per_round",
            "compute_end_cycles_per_round",
            "round_start_cycles",
            "round_end_cycles",
        ):
            metrics[key] = [value + origin for value in metrics[key]]
        row = analyze_rq3_results([cold])["latency_rows"][0]
        self.assertTrue(row["ledger_closed"])
        self.assertEqual(row["maintenance_cycles"], 20)
        self.assertEqual(row["resolve_app_overlap_cycles"], 22)

    def test_incorrect_and_non_spine_rows_are_excluded(self) -> None:
        incorrect = result("incorrect")
        incorrect["row"]["mathematical_correctness_mismatches"] = 1
        competitor = result("competitor")
        competitor["case"]["system"] = "grasu_regraph_k4_shared"
        self.assertEqual(
            analyze_rq3_results([incorrect, competitor])["work_rows"], []
        )

    def test_exact_duplicate_results_do_not_bias_regression(self) -> None:
        duplicate = result("same")
        analysis = analyze_rq3_results([duplicate, duplicate])
        self.assertEqual(len(analysis["work_rows"]), 1)

    def test_explicit_plugin_order_selects_one_version_per_execution(self) -> None:
        old = result("same")
        old["plugin_sha256"] = "a" * 64
        new = result("same")
        new["plugin_sha256"] = "b" * 64
        new["row"]["cycles"] = 90
        new["scalar_metrics"]["update_cycles"] = 90
        analysis = analyze_rq3_results(
            [old, new], preferred_plugin_sha256=["b" * 64, "a" * 64]
        )
        self.assertEqual(len(analysis["work_rows"]), 1)
        self.assertEqual(analysis["work_rows"][0]["plugin_sha256"], "b" * 64)
        self.assertEqual(analysis["latency_rows"][0]["total_cycles"], 90)

    def test_explicit_rq3_role_overrides_dataset_kind(self) -> None:
        holdout = result("role")
        holdout["row"]["dataset_kind"] = "synthetic"
        holdout["rq3_role"] = "trace_holdout"
        row = analyze_rq3_results([holdout])["work_rows"][0]
        self.assertEqual(row["role"], "trace_holdout")

    def test_linear_fit_reports_slope_and_r2(self) -> None:
        fit = linear_fit([(1, 3), (2, 5), (3, 7)])
        self.assertEqual(fit["samples"], 3)
        self.assertAlmostEqual(fit["slope"], 2.0)
        self.assertAlmostEqual(fit["intercept"], 1.0)
        self.assertAlmostEqual(fit["r2"], 1.0)

    def test_e2e_model_fits_only_calibration_and_scores_holdout(self) -> None:
        features = (
            "w_sort_records",
            "w_carry_records",
            "directory_requests",
            "m_phys_records",
            "m_seed_records",
            "switch_work",
            "source_and_reactivation_work",
            "algorithm_apply_operations",
        )
        coefficients = (2, 3, 5, 7, 11, 13, 17, 23)
        rows = []
        for index in range(len(features) + 1):
            values = [0] * len(features)
            if index:
                values[index - 1] = 1
            rows.append(
                {
                    "execution_id": f"calib-{index}",
                    "dataset_id": "synthetic",
                    "algorithm": "weighted_sssp",
                    "case_class": "deep_carry",
                    "dataset_kind": "synthetic",
                    "role": "synthetic_calibration",
                    "total_cycles": 19 + sum(
                        value * coefficient
                        for value, coefficient in zip(values, coefficients, strict=True)
                    ),
                    **dict(zip(features, values, strict=True)),
                }
            )
        for index, scale in enumerate((2, 3)):
            values = [scale] * len(features)
            rows.append(
                {
                    "execution_id": f"holdout-{index}",
                    "dataset_id": "trace",
                    "algorithm": "connected_components",
                    "case_class": "shallow_insertion",
                    "dataset_kind": "real",
                    "role": "trace_holdout",
                    "total_cycles": 19 + sum(
                        value * coefficient
                        for value, coefficient in zip(values, coefficients, strict=True)
                    ),
                    **dict(zip(features, values, strict=True)),
                }
            )
        model, predictions, metrics = fit_e2e_cost_model(rows)
        self.assertEqual(model["status"], "fit")
        self.assertTrue(model["full_rank"])
        self.assertEqual(model["calibration_samples"], len(features) + 1)
        self.assertTrue(model["holdout_rows_are_never_used_for_fit"])
        self.assertLess(max(row["absolute_percent_error"] for row in predictions), 1e-6)
        self.assertLess(metrics[1]["mape_percent"], 1e-6)

    def test_writer_emits_machine_readable_tables(self) -> None:
        analysis = analyze_rq3_results([result()])
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            write_rq3_analysis(output, analysis)
            self.assertTrue((output / "rq3_summary.json").is_file())
            self.assertTrue((output / "rq3_work_rows.csv").is_file())
            self.assertTrue((output / "rq3_latency_rows.csv").is_file())
            self.assertTrue((output / "rq3_regression_rows.csv").is_file())
            self.assertTrue((output / "rq3_e2e_model.json").is_file())
            self.assertTrue((output / "rq3_e2e_prediction_rows.csv").is_file())
            self.assertTrue((output / "rq3_e2e_metric_rows.csv").is_file())
            self.assertTrue((output / "rq3_representative_rows.csv").is_file())
            self.assertTrue((output / "rq3_coverage_rows.csv").is_file())

    def test_raw_per_round_evidence_is_hash_verified(self) -> None:
        case = result("raw")
        with tempfile.TemporaryDirectory() as temporary:
            raw = dict(case["scalar_metrics"])
            raw["processed_edges_per_round"] = [7, 5]
            payload = (json.dumps(raw) + "\n").encode("ascii")
            for name in ("summary.json", "summary.json.gz"):
                with self.subTest(name=name):
                    raw_path = Path(temporary) / name
                    raw_path.write_bytes(gzip.compress(payload, mtime=0)
                                         if name.endswith(".gz") else payload)
                    case["raw_result_path"] = str(raw_path)
                    case["raw_result_sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
                    work = analyze_rq3_results([case])["work_rows"][0]
                    self.assertEqual(work["m_phys_records"], 12)
                    raw_path.write_text("{}\n", encoding="ascii")
                    with self.assertRaisesRegex(ValueError, "changed"):
                        analyze_rq3_results([case])


if __name__ == "__main__":
    unittest.main()
