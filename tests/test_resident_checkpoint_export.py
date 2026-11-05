"""Incomplete exports retain pending slots and do not invent propagation or repetitions."""

import importlib.util
from pathlib import Path
import sys
import unittest


class ResidentCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/figure7_11_preview_20261105")
        sys.path.insert(0, str(folder))
        try:
            spec = importlib.util.spec_from_file_location("resident_checkpoint", folder / "export_resident_checkpoint.py")
            cls.export = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.export)
        finally:
            sys.path.remove(str(folder))

    def row(self, **changes):
        pair = dict(algorithm="residual_pagerank", logical_updates=8, physical_updates=8,
                    spine_wall_ms=5, gr_wall_ms=10, speedup_gr_over_spine=2,
                    boundary="resident", spine_rounds=0, gr_rounds=0)
        pair.update(changes)
        return self.export.measured_row("residual_pagerank", "AU", pair,
            dict(sha256="receipt"), [140, 500, 430, 0], reused=True)

    def test_reused_zero_round_sample_is_not_fresh_pair_or_timing_closure(self):
        row = self.row()
        self.assertEqual((row["fresh_spine_samples"], row["fresh_gr_samples"]), (1, 0))
        self.assertTrue(row["gr_sample_reused"])
        self.assertFalse(row["nominal_timing_pass"])
        self.assertEqual((row["spine_rounds"], row["gr_rounds"]), (0, 0))

    def test_invalid_values_and_changed_batch_rejected(self):
        for changes in (dict(spine_wall_ms=0), dict(gr_wall_ms=float("nan")),
                        dict(speedup_gr_over_spine=3), dict(logical_updates=9)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.row(**changes)

    def test_different_round_counts_do_not_alone_disprove_same_final_state(self):
        self.assertEqual(self.row(spine_rounds=1, gr_rounds=2)["gr_rounds"], 2)

    def test_losing_row_is_retained(self):
        row = self.row(spine_wall_ms=20, speedup_gr_over_spine=0.5)
        self.assertEqual(row["speedup_gr_over_spine"], 0.5)


if __name__ == "__main__":
    unittest.main()
