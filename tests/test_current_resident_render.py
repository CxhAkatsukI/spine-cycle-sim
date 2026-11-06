"""A direct measured CC overlay leaves the frozen checkpoint and losses intact."""

import csv
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "requires the evaluation plotting environment")
class CurrentResidentRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/figure7_11_preview_20261105")
        sys.path.insert(0, str(folder))
        try:
            spec = importlib.util.spec_from_file_location("current_resident_render", folder / "render_current.py")
            cls.render = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.render)
        finally:
            sys.path.remove(str(folder))

    def fixture(self, root):
        rows = [dict(algorithm=algorithm, dataset=dataset, status="MEASURED", spine_wall_ms="2",
                     gr_wall_ms="4", speedup_gr_over_spine="2", routing_report_complete="True")
                for algorithm in self.render.LABELS for dataset in self.render.DATASETS]
        cc = [dict(row, status=self.render.CC_MEASURED, routing_report_complete="False")
              for row in rows if row["algorithm"] == "cc"]
        for row in rows:
            if row["algorithm"] == "cc":
                row.update(status="PENDING", spine_wall_ms="", gr_wall_ms="", speedup_gr_over_spine="")
        checkpoint, direct = root / "checkpoint.csv", root / "cc.csv"
        self.write(checkpoint, rows)
        self.write(direct, cc)
        return checkpoint, direct, rows, cc

    def write(self, path, rows):
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_overlay_keeps_losses_qualifications_and_frozen_source(self):
        with tempfile.TemporaryDirectory() as folder:
            checkpoint, direct, _, cc = self.fixture(Path(folder))
            original = checkpoint.read_bytes()
            cc[0].update(gr_wall_ms="1", speedup_gr_over_spine="0.5")
            cc[1].update(status="FAILED", spine_wall_ms="", gr_wall_ms="", speedup_gr_over_spine="")
            self.write(direct, cc)
            result = self.render.resident_rows(checkpoint, direct)
            self.assertEqual(checkpoint.read_bytes(), original)
            self.assertEqual(result[8]["speedup_gr_over_spine"], "0.5")
            self.assertEqual(result[8]["status"], self.render.CC_MEASURED)
            self.assertEqual(result[9]["status"], "FAILED")
            self.assertEqual(len(result), 24)

    def test_rejects_replacement_wrong_scope_and_inconsistent_times(self):
        for fault in ("replace", "missing", "duplicate", "qualification", "ratio", "failed-time"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as folder:
                checkpoint, direct, rows, cc = self.fixture(Path(folder))
                if fault == "replace":
                    rows[8] = dict(cc[0], status="MEASURED")
                elif fault == "missing":
                    cc.pop()
                elif fault == "duplicate":
                    cc[-1] = cc[0]
                elif fault == "qualification":
                    cc[0]["routing_report_complete"] = "True"
                elif fault == "ratio":
                    cc[0]["speedup_gr_over_spine"] = "3"
                else:
                    cc[0]["status"] = "FAILED"
                self.write(checkpoint, rows)
                self.write(direct, cc)
                with self.assertRaises(ValueError):
                    self.render.resident_rows(checkpoint, direct)


if __name__ == "__main__":
    unittest.main()
