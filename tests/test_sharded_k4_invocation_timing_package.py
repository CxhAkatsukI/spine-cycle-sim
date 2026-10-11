"""Recompute invocation diagnostics from the sealed six-row matrix."""

import json
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.invocation_timing import analyze_package


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst/empty_exit_matrix"


class InvocationTimingPackageTests(unittest.TestCase):
    def test_saved_diagnostic_is_reproducible_without_external_runs(self):
        saved = json.loads((PACKAGE / "invocation_timing.json").read_text())
        self.assertEqual(saved, analyze_package(PACKAGE))
        self.assertFalse(saved["hardware_timing_admitted"])
        self.assertFalse(saved["timing_fit_performed"])
        self.assertEqual(len(saved["rows"]), 6)

    def test_wk_gap_is_per_worker_and_queued_before_previous_completion(self):
        saved = json.loads((PACKAGE / "invocation_timing.json").read_text())
        row = next(r for r in saved["rows"] if r["id"] == "wk_candidate")
        group = next(g for g in row["groups"] if g["stage"] == "adapter" and g["worker"] == 0)
        self.assertEqual([x["partition"] for x in group["invocations"]], [0, 4, 8, 12, 16])
        self.assertAlmostEqual(group["board_gap_sum_ms"], 27.714, places=3)
        self.assertEqual(group["model_gap_sum_ms"], 0)
        self.assertTrue(all(x["queued_before_previous_end"] for x in group["invocations"][1:]))
        self.assertNotIn("total_gap_penalty_ms", row)


if __name__ == "__main__":
    unittest.main()
