"""The two Fig. 8 panels must retain one checked L4 host cohort."""

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "plotting dependency unavailable")
class HeadroomPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/figure7_11_preview_20261105/render.py")
        spec = importlib.util.spec_from_file_location("headroom_preview", source)
        cls.render = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.render)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.data = self.root / "fresh_simulator/portable_fig8_headroom_v1"
        (self.data / "batch_sweep").mkdir(parents=True)
        self.cohort = dict(cpu=20, spine_preload_minimum_level=4)
        rows = [dict(dataset=name, spine_preload_minimum_level=4, value=None)
                for name in ("AU", "SU", "WK", "SO", "PK")]
        sweep = [dict(batches=count, spine_preload_minimum_level=4)
                 for count in (10, 100, 1000)]
        self.scope = dict(status="COMPLETE", cohort=self.cohort,
                          reference_sha256="same", cases=rows)
        self.scope_path = self.data / "scope.json"
        self.scope_path.write_text(json.dumps(self.scope))
        self.sweep = dict(status="COMPLETE", cohort=dict(self.cohort),
                          reference_sha256="same", cases=sweep,
                          dataset_scope_sha256=hashlib.sha256(self.scope_path.read_bytes()).hexdigest())
        for path, cases in ((self.data / "fig8_ten_batch.csv", rows),
                            (self.data / "batch_sweep/fig8_batch_sensitivity.csv", sweep)):
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(cases[0]))
                writer.writeheader()
                writer.writerows(cases)

    def draw(self):
        (self.data / "batch_sweep/scope.json").write_text(json.dumps(self.sweep))
        with patch.object(self.render, "ROOT", self.root), patch.object(
                self.render, "fig8_persistent") as draw:
            self.render.fig8_headroom(self.root / "figures")
            return draw

    def test_matching_complete_panels_use_shared_renderer(self):
        self.draw().assert_called_once_with(self.root / "figures", self.data,
            "fig8_update_prediction_headroom",
            sweep_path=self.data / "batch_sweep/fig8_batch_sensitivity.csv")

    def test_changed_host_affinity_or_initialization_is_rejected(self):
        for change in (dict(cpu=21), dict(spine_preload_minimum_level=2)):
            with self.subTest(change=change):
                self.sweep["cohort"] = dict(self.cohort, **change)
                with self.assertRaisesRegex(ValueError, "matching L4"):
                    self.draw()

    def test_pending_panel_is_not_a_complete_prediction(self):
        self.sweep["status"] = "PARTIAL_RETAINED"
        with self.assertRaisesRegex(ValueError, "matching L4"):
            self.draw()

    def test_changed_scope_identity_is_rejected(self):
        self.sweep["dataset_scope_sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "matching L4"):
            self.draw()

    def test_changed_csv_is_rejected(self):
        path = self.data / "fig8_ten_batch.csv"
        path.write_text(path.read_text().replace("AU,4,", "AU,4,999"))
        with self.assertRaisesRegex(ValueError, "CSV differs"):
            self.draw()


if __name__ == "__main__":
    unittest.main()
