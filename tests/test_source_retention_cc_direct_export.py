import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import cc_direct_export as export


class DirectCCExportTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.paths = [self.root / name for name in ("matrix.json", "au.json", "gr.json")]
        self.case = dict(vertices=10, edges=20, updates=16)
        self.matrix = dict(status="COMPLETED_WITH_FAILURES", repetitions_per_arm=1, warmups=0,
                           bdf="board", artifacts={}, boundary="window", memory_profile="profile",
                           memory_peak_bytes=123, memory_events="oom 0",
                           cases={dataset: dict(status="FAILED", error="timeout")
                                  for dataset in export.DATASETS if dataset != "AU"})
        self.au = dict(execution=dict(exit_code=0), workload=self.case, stdout={}, clock_evidence={})
        self.reference = dict(dataset="AU", case=self.case, arms=dict(gr={}))

    def write(self):
        for path, value in zip(self.paths, (self.matrix, self.au, self.reference)):
            path.write_text(json.dumps(value))

    @patch.object(export, "measured")
    def test_failures_have_no_numeric_substitution_and_au_reuse_is_explicit(self, measured):
        measured.return_value = (dict(dataset="AU", gr_sample_reused=True), dict(gr_over_spine=1.2))
        self.write()
        rows, scope = export.collect(*self.paths)
        self.assertEqual([row["dataset"] for row in rows], list(export.DATASETS))
        self.assertEqual(scope["measured_pairs"], 1)
        self.assertEqual(scope["status"], "COMPLETED_WITH_FAILURES")
        self.assertTrue(rows[0]["gr_sample_reused"])
        for row in rows[1:]:
            self.assertEqual(row["error"], "timeout")
            self.assertNotIn("speedup_gr_over_spine", row)
        self.assertTrue(measured.call_args.kwargs["reused"])

    def test_running_campaign_cannot_be_delivered_as_terminal(self):
        self.matrix["status"] = "RUNNING"
        self.write()
        with self.assertRaisesRegex(ValueError, "terminal seven-case"):
            export.collect(*self.paths)

    def test_omitted_dataset_is_rejected(self):
        del self.matrix["cases"]["SO"]
        self.write()
        with self.assertRaisesRegex(ValueError, "terminal seven-case"):
            export.collect(*self.paths)

    def test_au_workload_mismatch_is_rejected(self):
        self.reference["case"] = dict(self.case, vertices=11)
        self.write()
        with self.assertRaisesRegex(ValueError, "AU workloads differ"):
            export.collect(*self.paths)

    @patch.object(export.clocks, "replay")
    @patch.object(export.cc_resident_results, "analyze")
    def test_raw_times_and_each_arms_own_clock_are_exported(self, analyze, replay):
        path = self.root / "stdout.txt"
        path.write_text("raw output")
        pair = dict(boundary="window", spine_ms=2., gr_ms=5., gr_over_spine=2.5,
                    spine_rounds=2, gr_supersteps=3, spine_hot_layout=True)
        analyze.return_value = pair
        images = dict(spine_image=dict(path="spine"), gr_image=dict(path="gr"))
        replay.side_effect = [dict(bdf="board", binary=images[name + "_image"],
                                   driver_reported_mhz=values)
                              for name, values in (("spine", [150, 500, 450]), ("gr", [140, 500, 430]))]
        arms = {name: dict(stdout=dict(path=str(path)), clock_evidence={}) for name in ("spine", "gr")}
        row, result = export.measured("WK", self.case, arms, "board", images)
        self.assertEqual(result, pair)
        self.assertEqual(row["speedup_gr_over_spine"], 2.5)
        self.assertEqual((row["spine_data_mhz"], row["gr_data_mhz"]), (150, 140))
        self.assertEqual(row["fresh_gr_samples"], 1)
        self.assertFalse(row["routing_report_complete"])


if __name__ == "__main__":
    unittest.main()
