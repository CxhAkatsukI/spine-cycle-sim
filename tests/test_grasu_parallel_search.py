import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.parallel.analysis import summarize
from spine_cycle_sim.experiments.evaluation_impact.common_g.parallel.delivery import completed_matrix, verify_pins
from spine_cycle_sim.experiments.evaluation_impact.common_g.parallel.preparation import CASES, segments
from spine_cycle_sim.experiments.evaluation_impact.common_g.parallel.validation import validate_matrix


class ParallelSearchMatrixTests(unittest.TestCase):
    def report(self):
        return {"errors": [], "hardware_timing_admitted": False,
                "publication_match_admitted": False, "production_baseline_admitted": False,
                "matrix": [(latency, name, count, arm) for latency in (64, 128)
                           for name, count, _ in CASES for arm in ("original", "current", "parallel")],
                "rows": [{"latency": latency, "case": name, "updates": count, "arm": arm,
                    "state_sha256": "a" * 64, "observation": {"arm": arm, "state_pass": True,
                        "timing_kind": "declared_prediction", "cycles": 100,
                        "read_bytes": count * 8, "write_bytes": 0,
                        "cache_updates": count, "ddr_updates": 0, "row_reads": count, "binary_probes": 0}}
                    for latency in (64, 128) for name, count, _ in CASES
                    for arm in ("original", "current", "parallel")]}

    def test_full_matrix_is_prediction_only(self):
        validate_matrix(self.report())
        self.assertTrue(summarize(self.report()["rows"], {"rows": []})["within_ten_percent_both_directions"])

    def test_larger_amortized_batches_not_omitted(self):
        self.assertEqual({count for _, count, _ in CASES if count >= 8192}, {8192, 16384, 65536})
        for _, count, kind in CASES:
            self.assertEqual(len(segments(count, kind)), count)
        self.assertEqual(set(segments(257, "conflict")), {0})

    def test_entire_missing_case_and_duplicate_rejected(self):
        for rows in (self.report()["rows"][3:], self.report()["rows"] + self.report()["rows"][:1]):
            report = self.report(); report["rows"] = rows
            with self.assertRaisesRegex(ValueError, "matrix row"):
                validate_matrix(report)

    def test_declared_scope_cannot_be_reduced(self):
        report = self.report(); report["matrix"] = report["matrix"][3:]
        with self.assertRaisesRegex(ValueError, "declared candidate"):
            validate_matrix(report)

    def test_bad_work_or_hardware_claim_rejected(self):
        for mutation in ("work", "hardware", "failure"):
            report = self.report()
            if mutation == "work": report["rows"][1]["observation"]["row_reads"] += 1
            elif mutation == "hardware": report["hardware_timing_admitted"] = True
            else: report["errors"].append({"error": "retained"})
            with self.assertRaises(ValueError): validate_matrix(report)

    def test_logical_difference_not_called_speedup(self):
        rows = self.report()["rows"]
        for field in ("state_sha256", "binary_probes"):
            changed = copy.deepcopy(rows)
            if field == "state_sha256": changed[2][field] = "b" * 64
            else: changed[2]["observation"][field] += 1
            with self.assertRaises(ValueError): summarize(changed, {"rows": []})

    def test_faster_is_not_automatically_two_sided_match(self):
        rows = self.report()["rows"]
        for row in rows:
            if row["arm"] == "parallel": row["observation"]["cycles"] = 50
        result = summarize(rows, {"rows": []})
        self.assertTrue(result["prediction_no_more_than_ten_percent_slower"])
        self.assertFalse(result["within_ten_percent_both_directions"])

    def test_empty_overhead_control_is_not_a_performance_gate(self):
        rows = self.report()["rows"]
        for row in rows:
            if not row["updates"] and row["arm"] == "parallel":
                row["observation"]["cycles"] = 0
        result = summarize(rows, {"rows": []})
        self.assertTrue(result["prediction_no_more_than_ten_percent_slower"])
        self.assertTrue(result["within_ten_percent_both_directions"])

    def test_packager_rechecks_summary_and_frozen_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "previous.json"; previous.write_text('{"rows": []}')
            report = self.report()
            report.update(summarize(report["rows"], {"rows": []}))
            report.update(status="PREDICTION_AND_SOURCE_HELPERS_PASS_NOT_HARDWARE_ADMISSION",
                          pins=[{"path": str(previous), "sha256": sha256_file(previous)}])
            path = root / "report.json"; path.write_text(json.dumps(report))
            self.assertEqual(completed_matrix(path, previous)["default_regression_rows"], 0)
            report["comparisons"][0]["parallel_over_original"] = 42
            path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "summary differs"):
                completed_matrix(path, previous)
            previous.write_text('{"rows": [], "changed": true}')
            with self.assertRaisesRegex(ValueError, "frozen evidence changed"):
                verify_pins(report["pins"])

    def test_committed_capsules_are_complete_and_not_promoted(self):
        folder = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/parallel_search/evidence")
        index = json.loads((folder / "index.json").read_text())
        for entry in index["reports"]:
            self.assertEqual(sha256_file(folder / entry["file"]), entry["sha256"])
        report = json.loads((folder / "matrix.json").read_text())
        previous = json.loads((folder / "previous_g.json").read_text())
        validate_matrix(report)
        summary = summarize(report["rows"], previous)
        self.assertEqual(summary["comparisons"], index["comparisons"])
        self.assertEqual(index["prediction_rows"], 84)
        self.assertEqual(index["default_regression_rows"], 12)
        self.assertFalse(index["baseline_admitted"])
        self.assertFalse(index["prediction_no_more_than_ten_percent_slower"])
        self.assertTrue(all(not item["estimated_clock_target_met"] for item in index["synthesis"]))

    def test_validated_runner_replay_preserves_all_84_observations(self):
        folder = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/parallel_search/evidence")
        replay = folder / "final_validation"
        index = json.loads((replay / "index.json").read_text())
        for entry in index["reports"]:
            self.assertEqual(sha256_file(replay / entry["file"]), entry["sha256"])
        first = json.loads((folder / "matrix.json").read_text())
        repeated = json.loads((replay / "matrix.json").read_text())
        validate_matrix(repeated)
        self.assertEqual(first["rows"], repeated["rows"])
        previous = json.loads((replay / "previous_g.json").read_text())
        summary = summarize(repeated["rows"], previous)
        self.assertEqual(summary["comparisons"], index["comparisons"])
        self.assertFalse(index["baseline_admitted"])
        self.assertFalse(index["hardware_timing_admitted"])
        self.assertFalse(index["publication_match_admitted"])
        self.assertFalse(index["new_spine_comparison_executed"])


if __name__ == "__main__":
    unittest.main()
