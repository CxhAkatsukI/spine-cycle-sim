from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.fpga_plot import (
    BOUNDARY, DATASETS, STYLES, digest, load_delivery,
)


class CacheExtentFpgaPlotTests(unittest.TestCase):
    """Synthetic parser fixtures are not FPGA evidence or published figures."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rows = []
        cases = []
        for algorithm, *_ in STYLES:
            for dataset in DATASETS:
                self.rows.append({
                    "algorithm": algorithm, "dataset": dataset, "status": "RESIDENT_PAIR_PASS",
                    "gr_ms": "1", "spine_ms": "4", "speedup_gr_over_spine": "0.25",
                })
                cases.append({
                    "algorithm": algorithm, "dataset": dataset, "status": "RESIDENT_PAIR_PASS",
                    "summary": {"walls": {"gr": {"median_ms": 1}, "spine": {"median_ms": 4}},
                                "speedup_ratio_of_median_walls": 0.25},
                })
        self.matrix = {"status": "FPGA_MATRIX_PASS", "passed_cases": 24, "cases": cases}
        self.plan = {"boundary": BOUNDARY, "repeats": {"warmup_pairs": 1, "measured_pairs": 3}}
        self.save()

    def save(self):
        (self.root / "matrix.json").write_text(json.dumps(self.matrix))
        (self.root / "plan.json").write_text(json.dumps(self.plan))
        (self.root / "files.json").write_text(json.dumps([
            {"path": name, "sha256": digest(self.root / name)}
            for name in ("matrix.json", "plan.json")
        ]))
        with (self.root / "summary.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=self.rows[0].keys())
            writer.writeheader()
            writer.writerows(self.rows)

    def test_preserves_all_24_rows_and_slowdowns(self):
        rows = load_delivery(self.root)
        self.assertEqual(len(rows), 24)
        self.assertTrue(all(float(row["speedup_gr_over_spine"]) == 0.25 for row in rows))

    def test_rejects_pending_matrix(self):
        self.matrix["status"] = "WAITING_FOR_REMAINING_HARDWARE"
        self.save()
        with self.assertRaisesRegex(ValueError, "terminal"):
            load_delivery(self.root)

    def test_rejects_changed_indexed_file(self):
        (self.root / "plan.json").write_text(json.dumps({**self.plan, "extra": 1}))
        with self.assertRaisesRegex(ValueError, "changed delivery"):
            load_delivery(self.root)

    def test_rejects_duplicate_or_missing_case(self):
        self.rows[0] = dict(self.rows[1])
        self.save()
        with self.assertRaisesRegex(ValueError, "24 unique"):
            load_delivery(self.root)

    def test_rejects_edited_ratio_and_nonfinite_time(self):
        for key, value in (("speedup_gr_over_spine", "10"), ("gr_ms", "nan")):
            with self.subTest(key=key):
                original = self.rows[0][key]
                self.rows[0][key] = value
                self.save()
                with self.assertRaises(ValueError):
                    load_delivery(self.root)
                self.rows[0][key] = original

    def test_retains_failure_but_rejects_a_failed_speedup(self):
        self.matrix.update(status="FPGA_MATRIX_INCOMPLETE_RETAINED", passed_cases=23)
        self.matrix["cases"][0]["status"] = "FAILED_RETAINED"
        self.rows[0]["status"] = "FAILED_RETAINED"
        self.save()
        with self.assertRaisesRegex(ValueError, "cannot contain speedups"):
            load_delivery(self.root)
        for key in ("gr_ms", "spine_ms", "speedup_gr_over_spine"):
            self.rows[0][key] = ""
        self.save()
        self.assertEqual(load_delivery(self.root)[0]["status"], "FAILED_RETAINED")

    def test_rejects_a_changed_measurement_boundary(self):
        self.plan["boundary"] = "device_only"
        self.save()
        with self.assertRaisesRegex(ValueError, "measurement contract"):
            load_delivery(self.root)

    def test_rejects_a_miscounted_pass(self):
        self.matrix["passed_cases"] = 23
        self.save()
        with self.assertRaisesRegex(ValueError, "passing-case count"):
            load_delivery(self.root)


if __name__ == "__main__":
    unittest.main()
