import copy
import json
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.hot_lanes.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.hot_lanes.preparation import ARMS, CASES, selected
from spine_cycle_sim.experiments.evaluation_impact.common_g.parallel.preparation import CASES as OLD_CASES


class HotOwnerMatrixTests(unittest.TestCase):
    def fixture(self):
        report = {"errors": [], "hardware_timing_admitted": False,
            "publication_match_admitted": False, "production_baseline_admitted": False,
            "matrix": [(latency, name, count, arm) for latency in (64, 128)
                       for name, count, _ in CASES for arm in ARMS],
            "rows": [{"latency": latency, "case": name, "updates": count, "arm": arm,
                "state_sha256": "a" * 64, "observation": {"arm": arm, "state_pass": True,
                    "timing_kind": "declared_prediction", "cycles": 100,
                    "read_bytes": count * 128, "write_bytes": count * 64,
                    "cache_updates": count, "ddr_updates": 0, "row_reads": count, "binary_probes": count}}
                for latency in (64, 128) for name, count, _ in CASES for arm in ARMS]}
        previous = {"rows": copy.deepcopy([r for r in report["rows"]
            if r["case"] in {name for name, _, _ in OLD_CASES} and r["arm"] != "parallel_hot"])}
        return report, previous

    def test_complete_scope_and_prediction_kind(self):
        report, previous = self.fixture()
        result = analyze(report, previous)
        self.assertEqual(len(report["rows"]), 152)
        self.assertEqual(result["old_checkpoint_exact_rows"], 84)
        self.assertTrue(result["within_ten_percent_both_directions"])

    def test_large_conflicts_and_owner_aliases_are_declared(self):
        for _, count, kind in CASES:
            self.assertEqual(len(selected(count, kind)), count)
        self.assertEqual(set(selected(65536, "conflict")), {0})
        self.assertEqual({(value >> 1) & 15 for value in selected(4096, "alias")}, {0})

    def test_missing_duplicate_scope_reduction_and_old_drift_rejected(self):
        for kind in ("missing", "duplicate", "scope", "old"):
            report, previous = self.fixture()
            if kind == "missing": report["rows"].pop()
            if kind == "duplicate": report["rows"].append(report["rows"][0])
            if kind == "scope": report["matrix"].pop()
            if kind == "old": previous["rows"][0]["observation"]["cycles"] += 1
            with self.assertRaises(ValueError): analyze(report, previous)

    def test_hardware_promotion_and_free_traffic_rejected(self):
        for kind in ("promotion", "traffic", "work", "state", "failure"):
            report, previous = self.fixture()
            row = report["rows"][-1]
            if kind == "promotion": report["hardware_timing_admitted"] = True
            if kind == "traffic": row["observation"]["read_bytes"] -= 64
            if kind == "work": row["observation"]["binary_probes"] += 1
            if kind == "state": row["state_sha256"] = "b" * 64
            if kind == "failure": report["errors"].append({"error": "failed"})
            with self.assertRaises(ValueError): analyze(report, previous)

    def test_one_large_conflict_failure_cannot_be_hidden(self):
        report, previous = self.fixture()
        row = next(r for r in report["rows"] if r["case"] == "same_key_amortized" and r["arm"] == "parallel_hot")
        row["observation"]["cycles"] = 200
        result = analyze(report, previous)
        self.assertFalse(result["prediction_no_more_than_ten_percent_slower"])

    def test_capsule_keeps_predictions_separate_from_admission(self):
        folder = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hot_lanes/evidence")
        index = json.loads((folder / "index.json").read_text())
        for entry in index["reports"]:
            self.assertEqual(sha256_file(folder / entry["file"]), entry["sha256"])
        report = json.loads((folder / "matrix.json").read_text())
        previous = json.loads((folder / "previous_search.json").read_text())
        result = analyze(report, previous)
        self.assertEqual(result["comparisons"], index["comparisons"])
        self.assertEqual(index["prediction_rows"], 152)
        for field in ("baseline_admitted", "hardware_timing_admitted", "publication_match_admitted",
                      "new_spine_comparison_executed"):
            self.assertIs(index[field], False)


if __name__ == "__main__":
    unittest.main()
