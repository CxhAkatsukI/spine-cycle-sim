"""Reject misleading parity labels and invalid values in the current control export."""

import importlib.util
from pathlib import Path
import unittest


class CurrentControlExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/figure7_11_preview_20261105/export_controls.py")
        spec = importlib.util.spec_from_file_location("current_control_export", source)
        cls.export = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.export)

    def row(self, ratio, passed=True):
        return self.export.stage_row("residual_pagerank", "G", "fixture",
            dict(current_over_reference=ratio, at_most_15_percent_slower=passed),
            dict(sha256="fixed"), [140, 500, 430, 0], nominal_timing_pass=False)

    def test_faster_control_is_not_absolute_parity_or_nominal_timing_pass(self):
        row = self.row(0.57)
        self.assertTrue(row["at_most_15_percent_slower"])
        self.assertFalse(row["absolute_15_percent_parity"])
        self.assertFalse(row["nominal_timing_pass"])
        self.assertFalse(row["publication_throughput_reproduced"])

    def test_accepts_small_observed_slowdown(self):
        self.assertTrue(self.row(1.135)["absolute_15_percent_parity"])

    def test_rejects_missing_or_failed_gate_and_invalid_ratios(self):
        for ratio in (0, -1, 1.151, float("inf"), float("nan"), True, None):
            with self.subTest(ratio=ratio), self.assertRaises(ValueError):
                self.row(ratio)
        with self.assertRaises(ValueError):
            self.row(1, False)


if __name__ == "__main__":
    unittest.main()
