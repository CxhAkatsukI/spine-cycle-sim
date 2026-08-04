from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "analyze_refactor31_real_slice_transfer.py"
)
SPEC = importlib.util.spec_from_file_location("analyze_refactor31_transfer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AnalyzeRefactor31RealSliceTransferTests(unittest.TestCase):
    def setUp(self) -> None:
        self.thresholds = {
            "median_total_cycle_error_percent_max": 15,
            "max_total_cycle_error_percent_max": 30,
            "component_median_cycle_error_percent_max": 20,
            "workload_rank_spearman_min": 0.9,
        }

    def test_holdout_admission_accepts_summary_within_frozen_thresholds(self) -> None:
        summary = {
            "paired_median_abs_error_pct": 10.0,
            "paired_max_abs_error_pct": 20.0,
            "reader_median_abs_error_pct": 12.0,
            "compute_median_abs_error_pct": 15.0,
            "paired_spearman": 1.0,
        }
        admission = MODULE.evaluate_holdout_admission(summary, self.thresholds)
        self.assertEqual(admission["scope"], "frozen_holdout")
        self.assertTrue(admission["all"])

    def test_bad_holdout_cannot_be_hidden_by_good_calibration(self) -> None:
        holdout = {
            "paired_median_abs_error_pct": 35.0,
            "paired_max_abs_error_pct": 40.0,
            "reader_median_abs_error_pct": 25.0,
            "compute_median_abs_error_pct": 10.0,
            "paired_spearman": 1.0,
        }
        admission = MODULE.evaluate_holdout_admission(holdout, self.thresholds)
        self.assertFalse(admission["paired_median_error"])
        self.assertFalse(admission["paired_max_error"])
        self.assertFalse(admission["component_median_error"])
        self.assertFalse(admission["all"])

    def test_rank_failure_is_part_of_holdout_gate(self) -> None:
        summary = {
            "paired_median_abs_error_pct": 1.0,
            "paired_max_abs_error_pct": 2.0,
            "reader_median_abs_error_pct": 3.0,
            "compute_median_abs_error_pct": 4.0,
            "paired_spearman": -1.0,
        }
        admission = MODULE.evaluate_holdout_admission(summary, self.thresholds)
        self.assertFalse(admission["workload_rank"])
        self.assertFalse(admission["all"])


if __name__ == "__main__":
    unittest.main()
