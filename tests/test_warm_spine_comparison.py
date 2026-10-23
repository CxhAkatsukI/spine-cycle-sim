"""Exploratory speedups require complete common-state evidence."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.warm_comparison import analysis


class WarmComparisonTests(unittest.TestCase):
    def rows(self):
        rows = []
        for workload in ("smoke", "amazon"):
            for latency in (64, 128):
                for arm, reverse in (("gr", 0), ("gr", 1), ("spine", 0)):
                    rows.append(dict(workload=workload, latency=latency, arm=arm, reverse=reverse,
                        input=dict(updates=[[0, 90, 1]]), state_hashes=dict(old_state="old", final="new", expected="new"),
                        result=(dict(cycles=100, g_cycles=10, r_cycles=90) if arm == "gr" else dict(cycles=50))))
        return rows

    def test_complete_matrix_reports_both_directions(self):
        rows = self.rows()
        result = analysis.summarize(rows)
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0]["speedup_gr_over_spine"], 2)
        rows[2]["result"]["cycles"] = 200
        self.assertEqual(analysis.summarize(rows)[0]["speedup_gr_over_spine"], .5)

    def test_missing_or_duplicate_rows_cannot_hide_failure(self):
        rows = self.rows()
        with self.assertRaisesRegex(ValueError, "complete"):
            analysis.summarize(rows[:-1])
        with self.assertRaisesRegex(ValueError, "complete"):
            analysis.summarize(rows + [copy.deepcopy(rows[0])])

    def test_different_batch_old_state_or_final_state_is_rejected(self):
        for key in ("old_state", "expected", "final"):
            rows = self.rows()
            rows[2]["state_hashes"][key] = "other"
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "identical"):
                analysis.summarize(rows)
        rows = self.rows()
        rows[2]["input"]["updates"] = []
        with self.assertRaisesRegex(ValueError, "identical"):
            analysis.summarize(rows)

    def test_registration_order_must_preserve_cycles_and_counters(self):
        rows = self.rows()
        rows[1]["result"]["r_cycles"] += 1
        with self.assertRaisesRegex(ValueError, "registration"):
            analysis.summarize(rows)

    def test_raw_execution_and_full_state_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name in ("old_state", "expected", "final"):
                (directory / (name + ".u32le")).write_bytes(b"same")
            result = dict(arm="gr", cycles=100, correctness=True, ledger_closed=True)
            stdout = directory / "stdout.txt"
            stdout.write_text("WARM_INPUT {}\nWARM_RESULT " + json.dumps(result) + "\n")
            resources = dict(exit_code=0, timed_out=False, stdout=str(stdout))
            self.assertEqual(analysis.record(resources, directory, "smoke", 64, "gr", 0)["result"], result)
            (directory / "final.u32le").write_bytes(b"different")
            with self.assertRaisesRegex(ValueError, "Dijkstra"):
                analysis.record(resources, directory, "smoke", 64, "gr", 0)
            resources["timed_out"] = True
            with self.assertRaisesRegex(ValueError, "retained"):
                analysis.record(resources, directory, "smoke", 64, "gr", 0)


if __name__ == "__main__":
    unittest.main()
