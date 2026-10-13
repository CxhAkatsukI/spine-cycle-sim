import copy
import unittest

from tests import test_grasu_metadata_credits
from spine_cycle_sim.experiments.evaluation_impact.common_g.finite_search.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.finite_search.preparation import ARM, GEOMETRY, matrix
from spine_cycle_sim.experiments.evaluation_impact.common_g.finite_search.study import settings
from spine_cycle_sim.experiments.evaluation_impact.common_g.finite_search.verification import check_outcome


class FiniteSearchTests(unittest.TestCase):
    def fixture(self):
        previous, _ = test_grasu_metadata_credits.MetadataCreditsTests().fixture()
        previous["status"] = "G_METADATA_CREDIT_PREDICTIONS_VALIDATED"
        rows = copy.deepcopy(previous["rows"])
        for row in previous["rows"]:
            if row["arm"] == "cached_hot64_m32":
                new = copy.deepcopy(row)
                new["arm"] = new["observation"]["arm"] = ARM
                rows.append(new)
        return {**settings(), "rows": rows, "matrix": matrix(), "errors": [],
                "baseline_admitted": False}, previous

    def test_complete_scope_replay_and_prediction_only(self):
        report, previous = self.fixture()
        result = analyze(report, previous)
        self.assertEqual(len(matrix()), 228)
        self.assertEqual(result["exact_replayed_rows"], 190)
        self.assertEqual(len(result["comparisons"]), 38)
        self.assertTrue(result["within_ten_percent_both_directions"])
        self.assertFalse(result["baseline_admitted"])
        self.assertFalse(result["hardware_timing_admitted"])
        self.assertEqual(GEOMETRY["internal_channels_per_cu"], 339)
        self.assertEqual(GEOMETRY["internal_fifo_token_bits_per_cu"], 38608)

    def test_keep_performance_mismatches_without_selecting_rows(self):
        report, previous = self.fixture()
        row = report["rows"][-1]
        row["observation"]["cycles"] = 120
        row["diagnostics"]["metadata_port_cycles"] = [120] * 4
        result = analyze(report, previous)
        self.assertFalse(result["no_more_than_ten_percent_slower"])
        self.assertFalse(result["within_ten_percent_both_directions"])
        self.assertEqual(len(result["comparisons"]), 38)

    def test_fail_closed_on_scope_state_work_resources_and_admission(self):
        faults = ("missing", "duplicate", "matrix", "previous", "default", "diagnostics",
            "state", "traffic", "ledger", "bank", "geometry", "masters", "contexts", "budget",
            "nonmetadata", "burst", "reorder", "channel", "width", "hardware", "baseline", "failed",
            "publication", "production", "cache_timing")
        for fault in faults:
            with self.subTest(fault=fault):
                report, previous = self.fixture()
                row = report["rows"][-1]
                if fault == "missing": report["rows"].pop()
                if fault == "duplicate": report["rows"].append(row)
                if fault == "matrix": report["matrix"].pop()
                if fault == "previous": previous["rows"].pop()
                if fault == "default": report["rows"][0]["observation"]["cycles"] += 1
                if fault == "diagnostics": report["rows"][0]["diagnostics"]["dispatch_done"] += 1
                if fault == "state": row["state_sha256"] = "b" * 64
                if fault == "traffic": row["observation"]["read_bytes"] += 1
                if fault == "ledger": row["observation"]["row_reads"] += 1
                if fault == "bank": report["bank_credits"] = 64
                if fault == "geometry": report["finite_search_geometry"] = {}
                if fault == "masters": report["metadata_masters_per_cu"] = 2
                if fault == "contexts": report["new_arm_contexts_per_cu"] = 128
                if fault == "budget": report["metadata_credits_per_master"] = {}
                if fault == "nonmetadata": row["diagnostics"]["ports"][-1]["parent_limit"] = 64
                if fault == "burst": row["diagnostics"]["ports"][0]["burst_limit"] = 16
                if fault == "reorder": row["diagnostics"]["ports"][0]["reorder_limit"] = 16
                if fault == "channel": row["diagnostics"]["ports"][0]["channel"] = 1
                if fault == "width": row["diagnostics"]["ports"][0]["width"] = 64
                if fault == "hardware": report["hardware_timing_admitted"] = True
                if fault == "baseline": report["baseline_admitted"] = True
                if fault == "publication": report["publication_match_admitted"] = True
                if fault == "production": report["production_baseline_admitted"] = True
                if fault == "cache_timing": report["reference_cache_timing_admitted"] = True
                if fault == "failed": report["errors"].append("retained")
                with self.assertRaises(ValueError): analyze(report, previous)

    def test_verification_requires_expected_bounded_outcome(self):
        step = {"exit_code": 8, "timed_out": False, "memory_limit_gib": 2, "reserve_gib": 8}
        checked = check_outcome(step, 8, "retained_failure")
        self.assertEqual(checked["expected_exit_code"], 8)
        for field, value in (("exit_code", 0), ("timed_out", True),
                ("memory_limit_gib", 0), ("memory_limit_gib", -1),
                ("memory_limit_gib", 3), ("reserve_gib", 7)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                check_outcome({**step, field: value}, 8, "retained_failure")


if __name__ == "__main__":
    unittest.main()
