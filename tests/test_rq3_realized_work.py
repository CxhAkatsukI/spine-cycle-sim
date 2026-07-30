from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.rq3 import (
    analyze_rq3_results,
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

    def test_realized_work_uses_direct_execution_counters(self) -> None:
        row = analyze_rq3_results([result()])["work_rows"][0]
        self.assertEqual(row["w_sort_records"], 8)
        self.assertEqual(row["directory_requests"], 32)
        self.assertEqual(row["m_phys_records"], 16)
        self.assertEqual(row["m_seed_records"], 2)
        self.assertEqual(row["source_services"], 3)
        self.assertEqual(row["reactivations"], 1)
        self.assertEqual(row["case_class"], "shallow_insertion")

    def test_missing_persisted_counter_is_not_zero_net(self) -> None:
        cc = result("cc")
        cc["case"]["algorithm"] = "connected_components"
        del cc["scalar_metrics"]["maintenance_persisted_edges"]
        row = analyze_rq3_results([cc])["work_rows"][0]
        self.assertEqual(row["case_class"], "shallow_insertion")

    def test_zero_net_requires_explicit_execution_evidence(self) -> None:
        zero = result("zero")
        zero["scalar_metrics"]["maintenance_persisted_edges"] = 0
        analysis = analyze_rq3_results([zero])
        self.assertEqual(analysis["work_rows"][0]["case_class"], "zero_net")
        self.assertEqual(analysis["coverage_rows"][0]["status"], "ready")

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

    def test_linear_fit_reports_slope_and_r2(self) -> None:
        fit = linear_fit([(1, 3), (2, 5), (3, 7)])
        self.assertEqual(fit["samples"], 3)
        self.assertAlmostEqual(fit["slope"], 2.0)
        self.assertAlmostEqual(fit["intercept"], 1.0)
        self.assertAlmostEqual(fit["r2"], 1.0)

    def test_writer_emits_machine_readable_tables(self) -> None:
        analysis = analyze_rq3_results([result()])
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            write_rq3_analysis(output, analysis)
            self.assertTrue((output / "rq3_summary.json").is_file())
            self.assertTrue((output / "rq3_work_rows.csv").is_file())
            self.assertTrue((output / "rq3_latency_rows.csv").is_file())
            self.assertTrue((output / "rq3_regression_rows.csv").is_file())
            self.assertTrue((output / "rq3_representative_rows.csv").is_file())
            self.assertTrue((output / "rq3_coverage_rows.csv").is_file())

    def test_raw_per_round_evidence_is_hash_verified(self) -> None:
        case = result("raw")
        with tempfile.TemporaryDirectory() as temporary:
            raw_path = Path(temporary) / "summary.json"
            raw = dict(case["scalar_metrics"])
            raw["processed_edges_per_round"] = [7, 5]
            raw_path.write_text(json.dumps(raw) + "\n", encoding="ascii")
            case["raw_result_path"] = str(raw_path)
            case["raw_result_sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            work = analyze_rq3_results([case])["work_rows"][0]
            self.assertEqual(work["m_phys_records"], 12)
            raw_path.write_text("{}\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "changed"):
                analyze_rq3_results([case])


if __name__ == "__main__":
    unittest.main()
