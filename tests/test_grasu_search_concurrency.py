import copy
import unittest

from tests import test_grasu_cached_hot
from spine_cycle_sim.experiments.evaluation_impact.common_g.cached_hot.study import metadata
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_concurrency.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_concurrency.preparation import matrix


class SearchConcurrencyTests(unittest.TestCase):
    def fixture(self):
        old, _ = test_grasu_cached_hot.CachedHotMatrixTests().fixture()
        old["status"] = "CACHED_G_PREDICTION_VALIDATED_REFERENCE_TIMING_OPEN"
        report = {**metadata(), "matrix": matrix(), "errors": [], "rows": [],
            "search_contexts_per_cu": {"cached_hot": 16, "cached_hot64": 64,
                "original": 64, "original_forwarded": 64}}
        keyed = {(r["latency"], r["case"], r["arm"]): r for r in old["rows"]}
        for latency, name, count, arm in matrix():
            source = {"original_forwarded": "original", "cached_hot64": "cached_hot"}.get(arm, arm)
            row = copy.deepcopy(keyed[(latency, name, source)])
            row["arm"] = row["observation"]["arm"] = arm
            report["rows"].append(row)
        return report, old

    def test_complete_266_with_190_exact_unchanged(self):
        report, previous = self.fixture()
        result = analyze(report, previous)
        self.assertEqual(len(report["rows"]), 266)
        self.assertEqual(result["old_checkpoint_exact_rows"], 190)
        self.assertTrue(result["forwarded_reference_within_ten_percent_both_directions"])
        self.assertEqual(len(result["comparisons"]), 38)

    def test_scope_historical_drift_failure_and_unsupported_promotion(self):
        for fault in ("scope", "duplicate", "previous", "old", "error", "hardware", "ports"):
            with self.subTest(fault=fault):
                report, previous = self.fixture()
                if fault == "scope": report["matrix"].pop()
                if fault == "duplicate": report["rows"].append(report["rows"][0])
                if fault == "previous": previous["status"] = "RUNNING"
                if fault == "old": previous["rows"][-1]["observation"]["cycles"] += 1
                if fault == "error": report["errors"].append({"error": "bad"})
                if fault == "hardware": report["hardware_timing_admitted"] = True
                if fault == "ports": report["banks"] = 8
                with self.assertRaises(ValueError): analyze(report, previous)

    def test_new_control_work_state_time_and_traffic_cannot_be_omitted(self):
        for field in ("state_sha256", "cache_updates", "read_bytes", "write_bytes", "cycles", "arm"):
            with self.subTest(field=field):
                report, previous = self.fixture()
                row = report["rows"][-1]
                if field == "state_sha256": row[field] = "b" * 64
                elif field == "cycles": row["observation"][field] = 0
                elif field == "arm": row["observation"][field] = "cached_hot"
                else: row["observation"][field] += 1
                with self.assertRaises(ValueError): analyze(report, previous)

    def test_one_conflict_failure_does_not_pass_by_averaging(self):
        report, previous = self.fixture()
        row = next(r for r in report["rows"] if r["case"] == "same_key_amortized" and r["arm"] == "cached_hot64")
        row["observation"]["cycles"] = 111
        self.assertFalse(analyze(report, previous)["forwarded_reference_no_more_than_ten_percent_slower"])

    def test_changed_context_budget_cannot_be_reported_as_same_experiment(self):
        report, previous = self.fixture()
        report["search_contexts_per_cu"]["cached_hot64"] = 128
        with self.assertRaisesRegex(ValueError, "geometry"):
            analyze(report, previous)


if __name__ == "__main__":
    unittest.main()
