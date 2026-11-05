"""Fresh memory exports must not mix completed predictions with FPGA claims."""

import importlib.util
from pathlib import Path
import unittest


class FreshMemoryExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/figure7_11_preview_20261105/export_memory.py")
        spec = importlib.util.spec_from_file_location("fresh_memory_export", source)
        cls.export = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.export)

    def setUp(self):
        self.report = dict(status="COMPLETE_SUPPORTED_SCOPE", failures=[],
            pins_unchanged=True, baseline_admitted=False, rows=[
                dict(algorithm=a, dataset=d, status="PREDICTION_ONLY",
                     baseline_admitted=False, figure=9, updates=8)
                for a in ("SSSP", "CC", "ResPR") for d in ("AU", "SU", "WK")])

    def test_accepts_only_the_declared_nine_pairs(self):
        self.export.validate_scope(self.report)
        self.report["rows"].pop()
        with self.assertRaisesRegex(ValueError, "nine-pair"):
            self.export.validate_scope(self.report)

    def test_rejects_a_duplicate_instead_of_the_missing_pair(self):
        self.report["rows"][-1] = self.report["rows"][0].copy()
        with self.assertRaisesRegex(ValueError, "nine-pair"):
            self.export.validate_scope(self.report)

    def test_rejects_an_unproven_hardware_claim(self):
        self.report["rows"][0]["baseline_admitted"] = True
        with self.assertRaisesRegex(ValueError, "mixed timing evidence"):
            self.export.validate_scope(self.report)

    def test_rejects_a_different_update_batch(self):
        self.report["rows"][0]["updates"] = 512
        with self.assertRaisesRegex(ValueError, "input scope"):
            self.export.validate_scope(self.report)

    def test_rejects_changed_source_pins(self):
        self.report["pins_unchanged"] = False
        with self.assertRaisesRegex(ValueError, "unchanged"):
            self.export.validate_scope(self.report)


if __name__ == "__main__":
    unittest.main()
