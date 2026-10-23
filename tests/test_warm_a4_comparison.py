"""Same-batch baseline checks reject partial matrices and changed semantics."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.warm_comparison import a4_analysis
import test_warm_spine_comparison as warm_tests


class WarmA4Tests(unittest.TestCase):
    def rows(self):
        warm = warm_tests.WarmComparisonTests().rows()
        rows = []
        for source in warm:
            if source["arm"] != "gr":
                continue
            rows.append(dict(workload=source["workload"], latency=source["latency"],
                reverse=source["reverse"], input=copy.deepcopy(source["input"]),
                state_hashes=copy.deepcopy(source["state_hashes"]), replica_hashes=["same"] * 4,
                result=dict(cycles=100, read_bytes=1000, write_bytes=100), rounds=[dict(cycles=100)]))
        return rows, warm

    def test_all_rows_report_separate_r_ratio_and_spine_comparison(self):
        rows, warm = self.rows()
        result = a4_analysis.summarize(rows, warm)
        self.assertEqual(len(result), 4)
        self.assertAlmostEqual(result[0]["r_over_a4"], .9)
        self.assertTrue(result[0]["within_15pct"])
        self.assertEqual(result[0]["speedup_gr_over_spine"], 2)

    def test_outside_15pct_remains_reported_not_dropped(self):
        rows, warm = self.rows()
        rows[0]["result"]["cycles"] = rows[1]["result"]["cycles"] = 50
        result = a4_analysis.summarize(rows, warm)
        self.assertFalse(result[0]["within_15pct"])
        self.assertAlmostEqual(result[0]["r_delta_pct"], 80)

    def test_missing_duplicate_or_changed_batch_rejected(self):
        rows, warm = self.rows()
        with self.assertRaisesRegex(ValueError, "eight"):
            a4_analysis.summarize(rows[:-1], warm)
        rows[1]["reverse"] = 0
        with self.assertRaisesRegex(ValueError, "reverse"):
            a4_analysis.summarize(rows, warm)
        rows, warm = self.rows()
        for row in rows[:2]:
            row["input"]["updates"] = []
        with self.assertRaisesRegex(ValueError, "different common"):
            a4_analysis.summarize(rows, warm)

    def test_reverse_counter_or_state_changes_rejected(self):
        for key in ("result", "state_hashes", "replica_hashes"):
            rows, warm = self.rows()
            rows[1][key] = {}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "order"):
                a4_analysis.summarize(rows, warm)

    def test_raw_convergence_and_full_state_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name in ("old_state", "expected", "final", "replica0", "replica1", "replica2", "replica3"):
                (directory / (name + ".u32le")).write_bytes(b"same")
            result = dict(arm="a4_io16", passed=True, cycles=100, rounds=1)
            round_row = dict(arm="a4_io16", round=0, cycles=100, active=0)
            stdout = directory / "stdout.txt"
            stdout.write_text("WARM_INPUT {\"oracle_rounds\":1}\nDEMO_RESULT " + json.dumps(result) +
                              "\nDEMO_ROUND " + json.dumps(round_row) + "\n")
            step = dict(exit_code=0, timed_out=False, stdout=str(stdout))
            row = a4_analysis.a4_record(step, directory, "smoke", 64, 0)
            self.assertEqual(row["result"], result)
            (directory / "replica2.u32le").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "replicas"):
                a4_analysis.a4_record(step, directory, "smoke", 64, 0)


if __name__ == "__main__":
    unittest.main()
