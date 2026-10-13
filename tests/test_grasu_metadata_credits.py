import copy
import unittest

from tests import test_grasu_search_diagnostics as diagnostics
from spine_cycle_sim.experiments.evaluation_impact.common_g.metadata_credits.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.metadata_credits.preparation import ARMS, CREDITS, NEW_ARMS, matrix


class MetadataCreditsTests(unittest.TestCase):
    def fixture(self):
        previous, _ = diagnostics.SearchDiagnosticsTests().fixture()
        for row in previous["rows"]:
            for port in row["diagnostics"]["ports"]:
                port.update(burst_limit=16, reorder_limit=16, channel=0, width=8)
        previous["status"] = "G_READ_ONLY_DIAGNOSTICS_EXACT_REPLAY"
        rows = copy.deepcopy(previous["rows"])
        for row in previous["rows"]:
            if row["arm"] != "cached_hot64":
                continue
            for arm in NEW_ARMS:
                new = copy.deepcopy(row)
                new["arm"] = new["observation"]["arm"] = arm
                for port in new["diagnostics"]["ports"]:
                    if port["name"].startswith("grasu-row"):
                        for field in ("parent_limit", "burst_limit", "reorder_limit"):
                            port[field] = CREDITS[arm]
                rows.append(new)
        report = {**previous, "rows": rows, "matrix": matrix(),
            "metadata_credits_per_master": CREDITS, "metadata_masters_per_cu": 1,
            "new_arm_contexts_per_cu": 64}
        return report, previous

    def test_complete_190_row_scope_and_exact_114_row_replay(self):
        report, previous = self.fixture()
        self.assertEqual(len(matrix()), 190)
        self.assertEqual(len(ARMS), 5)
        result = analyze(report, previous)
        self.assertEqual(result["exact_replayed_rows"], 114)
        self.assertTrue(all(result["within_ten_percent_both_directions"].values()))
        self.assertFalse(result["baseline_admitted"])
        self.assertFalse(result["hardware_timing_admitted"])

    def test_no_row_selection_to_promote_performance(self):
        report, previous = self.fixture()
        row = report["rows"][-1]
        row["observation"]["cycles"] = 120
        row["diagnostics"]["metadata_port_cycles"] = [120] * 4
        result = analyze(report, previous)
        self.assertFalse(result["no_more_than_ten_percent_slower"][row["arm"]])
        self.assertFalse(result["within_ten_percent_both_directions"][row["arm"]])

    def test_reject_scope_defaults_resources_traffic_and_false_admission(self):
        for fault in ("missing", "duplicate", "matrix", "previous", "default", "diagnostics",
                      "state", "traffic", "ledger", "bank", "masters", "contexts", "budget",
                      "nonmetadata", "burst", "reorder", "channel", "width", "hardware", "baseline", "failed"):
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
                if fault == "failed": report["errors"].append("retained")
                with self.assertRaises(ValueError): analyze(report, previous)


if __name__ == "__main__":
    unittest.main()
