"""Invocation gaps are trace diagnostics, never exclusive stage costs."""

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages.invocation_timing import analyze_package, compare_invocations


def inputs():
    result = {"partitions": 5, "rounds": [{"start": 100}], "invocations": []}
    board = {"events": []}
    for stage in ("adapter", "gather"):
        for p in range(5):
            start = 100 + 150 * (p // 4)
            result["invocations"].append(dict(round=1, partition=p, worker=p % 4, stage=stage,
                                               start=start, end=start + 150))
            start_ns = 1000 + 10000 * (p // 4)
            board["events"].append(dict(round=0, shard=p, worker=p % 4, stage=stage,
                                        queued_ns=500, submit_ns=start_ns - 100,
                                        start_ns=start_ns, end_ns=start_ns + 1000))
    return result, board


class InvocationTimingTests(unittest.TestCase):
    def test_partial_matrix_cannot_be_packaged_as_complete(self):
        with TemporaryDirectory() as tmp:
            package = Path(tmp)
            report = {"status": "EMPTY_EXIT_REAL_MATRIX_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC",
                      "hardware_timing_admitted": False, "timing_fit_performed": False, "rows": []}
            (package / "matrix.json").write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                analyze_package(package)

    @patch("spine_cycle_sim.experiments.sharded_k4_stages.invocation_timing.timing_diagnostic", return_value={})
    def test_per_worker_gap_does_not_become_an_e2e_sum(self, _):
        report = compare_invocations(*inputs())
        group = report["groups"][0]
        self.assertEqual(group["board_gap_sum_ms"], .009)
        self.assertEqual(group["model_gap_sum_ms"], 0)
        second = group["invocations"][1]
        self.assertTrue(second["queued_before_previous_end"])
        self.assertAlmostEqual(second["submit_after_previous_end_ms"], .0089)
        self.assertAlmostEqual(second["start_after_submit_ms"], .0001)
        self.assertNotIn("total_gap_penalty_ms", report)

    @patch("spine_cycle_sim.experiments.sharded_k4_stages.invocation_timing.timing_diagnostic", return_value={})
    def test_missing_duplicate_or_wrong_worker_rejected(self, _):
        for mutate in (lambda x: x.pop(), lambda x: x.append(copy.deepcopy(x[0])),
                       lambda x: x[0].update(worker=3)):
            for side in ("model", "board"):
                r, b = inputs()
                mutate(r["invocations"] if side == "model" else b["events"])
                with self.subTest(side=side), self.assertRaises(ValueError):
                    compare_invocations(r, b)

    @patch("spine_cycle_sim.experiments.sharded_k4_stages.invocation_timing.timing_diagnostic", return_value={})
    def test_overlap_and_bad_timestamp_rejected(self, _):
        for side in ("model", "board"):
            r, b = inputs()
            if side == "model":
                r["invocations"][4]["start"] = 249
            else:
                b["events"][4]["start_ns"] = 1999
                b["events"][4]["submit_ns"] = 1000
            with self.subTest(side=side), self.assertRaises(ValueError):
                compare_invocations(r, b)


if __name__ == "__main__":
    unittest.main()
