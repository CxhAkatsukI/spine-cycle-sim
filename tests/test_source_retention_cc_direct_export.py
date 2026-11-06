from copy import deepcopy
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

    def resume(self):
        self.matrix["cases"]["LJ"].update(case=self.case, inputs="same-inputs")
        resumed = dict(deepcopy(self.matrix), cases={"LJ": deepcopy(self.matrix["cases"]["LJ"])},
                       arm_timeout_seconds=7200, memory_peak_bytes=456)
        self.write()
        path = self.root / "resume.json"
        path.write_text(json.dumps(resumed))
        return path, resumed

    def test_resume_replaces_only_failed_attempt_and_keeps_both_records(self):
        path, resumed = self.resume()
        cases, attempts = export._attempts(self.paths[0], self.matrix, path)
        self.assertEqual(cases["LJ"], resumed["cases"]["LJ"])
        self.assertEqual([entry[0] for entry in attempts], [self.paths[0], path])
        self.assertNotIn("arm_timeout_seconds", self.matrix)
        self.matrix["cases"]["LJ"]["status"] = export.MEASURED
        with self.assertRaisesRegex(ValueError, "already measured"):
            export._attempts(self.paths[0], self.matrix, path)

    def test_resume_cannot_change_image_boundary_or_workload(self):
        path, resumed = self.resume()
        for key, value in (("artifacts", dict(spine_image="different")), ("boundary", "different")):
            path.write_text(json.dumps(dict(resumed, **{key: value})))
            with self.assertRaisesRegex(ValueError, "configuration"):
                export._attempts(self.paths[0], self.matrix, path)
        resumed["cases"]["LJ"]["inputs"] = "different-inputs"
        path.write_text(json.dumps(resumed))
        with self.assertRaisesRegex(ValueError, "original workload"):
            export._attempts(self.paths[0], self.matrix, path)

    def test_running_resume_is_not_deliverable(self):
        path, resumed = self.resume()
        path.write_text(json.dumps(dict(resumed, status="RUNNING")))
        with self.assertRaisesRegex(ValueError, "terminal subset"):
            export._attempts(self.paths[0], self.matrix, path)

    def test_ordered_retries_preserve_failures_but_cannot_replace_a_valid_sample(self):
        path, resumed = self.resume()
        later = self.root / "retry-again.json"
        final = deepcopy(resumed)
        final["cases"]["LJ"].update(status=export.MEASURED, comparison={})
        later.write_text(json.dumps(final))
        cases, attempts = export._attempts(self.paths[0], self.matrix, [path, later])
        self.assertEqual(cases["LJ"]["status"], export.MEASURED)
        self.assertEqual([record["cases"]["LJ"]["status"] for _, record in attempts],
                         ["FAILED", "FAILED", export.MEASURED])
        with self.assertRaisesRegex(ValueError, "already measured"):
            export._attempts(self.paths[0], self.matrix, [path, later, later])

    @patch.object(export, "measured")
    def test_completed_retry_is_selected_and_memory_is_reported_per_attempt(self, measured):
        path, resumed = self.resume()
        pair = dict(gr_over_spine=2.)
        resumed["status"] = export.MEASURED
        resumed["cases"]["LJ"].update(status=export.MEASURED, arms={}, comparison=pair)
        path.write_text(json.dumps(resumed))
        measured.side_effect = lambda dataset, *args, **kwargs: (dict(dataset=dataset), pair)
        rows, scope = export.collect(*self.paths, resume_path=path)
        self.assertEqual(scope["measured_pairs"], 2)
        self.assertEqual(scope["memory_peak_bytes"], 456)
        self.assertEqual([row["arm_timeout_seconds"] for row in scope["attempts"]], [1800, 7200])
        self.assertEqual([row["memory_peak_bytes"] for row in scope["attempts"]], [123, 456])
        self.assertEqual([row["dataset"] for row in rows if "error" not in row], ["AU", "LJ"])
        self.assertEqual(len(scope["raw_source_records"]), 4)

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
