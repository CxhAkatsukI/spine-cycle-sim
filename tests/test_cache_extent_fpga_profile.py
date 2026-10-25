from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.fpga_plot import BOUNDARY, DATASETS, digest
from spine_cycle_sim.experiments.evaluation_impact.fpga_profile import (
    PREFIXES, SCOPE, inspect, package, sample_profile,
)


def timing(algorithm, wall=2, union=1.5, g=1, barrier=1, readback=0.1):
    # Synthetic intervals deliberately overlap; these are not FPGA evidence.
    fields = {"setup_inclusive_ms": wall, "adapter_ms": 1000}
    if algorithm == "respr":
        fields.update(update_ms=g, device_e2e_ms=union)
    else:
        fields.update(grasu_ms=g, event_e2e_ms=union, barrier_ms=barrier,
                      convergence_readback_ms=readback)
    return PREFIXES[algorithm] + " " + " ".join(f"{key}={value}" for key, value in fields.items())


class FpgaProfileSampleTests(unittest.TestCase):
    def test_keeps_overlapping_intervals_separate(self):
        result = sample_profile("sssp", timing("sssp"), 2)
        self.assertEqual(result["kernel_uncovered_wall_ms"], 0.5)
        self.assertGreater(result["g_event_union_ms"] + result["barrier_event_union_ms"],
                           result["kernel_event_union_ms"])
        self.assertNotIn("adapter_ms", result)

    def test_respr_does_not_invent_barrier_or_readback_measurements(self):
        result = sample_profile("respr", timing("respr"), 2)
        self.assertEqual(result["g_event_union_ms"], 1)
        self.assertNotIn("barrier_event_union_ms", result)
        self.assertNotIn("convergence_readback_ms", result)

    def test_rejects_missing_duplicate_or_malformed_record(self):
        valid = timing("cc")
        for text in ("", valid + "\n" + valid, valid + " grasu_ms=1", valid + " broken",
                     valid.replace("barrier_ms=1", "omitted=1")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                sample_profile("cc", text, 2)

    def test_rejects_negative_or_nonfinite_measurements(self):
        for value in (-1, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                sample_profile("respr", timing("respr", g=value), 2)

    def test_rejects_wall_mismatch_and_impossible_intervals(self):
        for text, expected in ((timing("sssp"), 3), (timing("sssp", union=3), 2),
                               (timing("sssp", g=1.6), 2), (timing("sssp", barrier=1.6), 2),
                               (timing("sssp", readback=3), 2)):
            with self.subTest(text=text, expected=expected), self.assertRaises(ValueError):
                sample_profile("sssp", text, expected)


class FpgaProfileDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "synthetic_delivery"
        self.root.mkdir()
        self.rows, cases = [], []
        self.indexed_logs = []
        for algorithm in PREFIXES:
            for dataset in DATASETS:
                self.rows.append({
                    "algorithm": algorithm, "dataset": dataset, "status": "RESIDENT_PAIR_PASS",
                    "gr_ms": "20", "spine_ms": "4", "speedup_gr_over_spine": "5",
                })
                cases.append({
                    "algorithm": algorithm, "dataset": dataset, "status": "RESIDENT_PAIR_PASS",
                    "summary": {"walls": {
                        "gr": {"median_ms": 20, "samples_ms": [10, 20, 30]},
                        "spine": {"median_ms": 4}}, "speedup_ratio_of_median_walls": 5},
                })
                for index, (wall, union) in enumerate(((999, 1), (10, 9), (20, 19), (30, 1))):
                    relative = f"cases/{algorithm}-{dataset.lower()}/sample-{index}/gr/run.log"
                    path = self.root / relative
                    path.parent.mkdir(parents=True)
                    path.write_text(timing(algorithm, wall, union, g=0.1, barrier=0.2))
                    self.indexed_logs.append(relative)
        self.matrix = {"status": "FPGA_MATRIX_PASS", "passed_cases": 24, "cases": cases}
        self.save()

    def save(self):
        (self.root / "matrix.json").write_text(json.dumps(self.matrix))
        (self.root / "plan.json").write_text(json.dumps({"boundary": BOUNDARY,
            "repeats": {"warmup_pairs": 1, "measured_pairs": 3}}))
        (self.root / "files.json").write_text(json.dumps([
            {"path": name, "sha256": digest(self.root / name)}
            for name in ("matrix.json", "plan.json", *self.indexed_logs)
        ]))
        with (self.root / "summary.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=self.rows[0].keys())
            writer.writeheader()
            writer.writerows(self.rows)

    def test_keeps_all_cases_and_computes_gap_before_taking_median(self):
        result = inspect(self.root)
        self.assertEqual(result["scope"], SCOPE)
        self.assertEqual(len(result["cases"]), 24)
        for row in result["cases"]:
            self.assertEqual([sample["sample_index"] for sample in row["samples"]], [1, 2, 3])
            self.assertEqual(row["median_ms"]["wall_ms"], 20)
            self.assertEqual(row["median_ms"]["kernel_event_union_ms"], 9)
            self.assertEqual(row["median_ms"]["kernel_uncovered_wall_ms"], 1)

    def test_rejects_unindexed_or_changed_log(self):
        relative = self.indexed_logs.pop(1)
        self.save()
        with self.assertRaisesRegex(ValueError, "unindexed profiling log"):
            inspect(self.root)
        self.indexed_logs.append(relative)
        self.save()
        (self.root / relative).write_text("modified")
        with self.assertRaisesRegex(ValueError, "changed delivery file"):
            inspect(self.root)

    def test_rejects_mixed_sample_wall_or_wrong_repetition_count(self):
        walls = self.matrix["cases"][0]["summary"]["walls"]["gr"]
        for values in ([11, 20, 30], [10, 20]):
            walls["samples_ms"] = values
            self.save()
            with self.assertRaises(ValueError):
                inspect(self.root)

    def test_preserves_failure_without_profile_or_zero_fill(self):
        self.matrix.update(status="FPGA_MATRIX_INCOMPLETE_RETAINED", passed_cases=23)
        self.matrix["cases"][0]["status"] = "FAILED_RETAINED"
        self.rows[0].update(status="FAILED_RETAINED", gr_ms="", spine_ms="", speedup_gr_over_spine="")
        self.save()
        row = inspect(self.root)["cases"][0]
        self.assertEqual(row, {"algorithm": "sssp", "dataset": "AU", "status": "FAILED_RETAINED"})

    def test_rejects_running_matrix(self):
        self.matrix["status"] = "RUNNING_FPGA_MATRIX"
        self.save()
        with self.assertRaisesRegex(ValueError, "terminal"):
            inspect(self.root)

    def test_packages_diagnostics_without_changing_inputs_or_overwriting(self):
        output = self.root.parent / "diagnostics"
        before = {path: digest(path) for path in self.root.rglob("*") if path.is_file()}
        report = package(self.root, output)
        self.assertEqual(json.loads((output / "profile.json").read_text()), report)
        self.assertIn("not pure host", (output / "README.md").read_text())
        with (output / "profile_medians.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 24)
        respr = next(row for row in rows if row["algorithm"] == "respr")
        self.assertEqual(respr["barrier_event_union_ms"], "")
        self.assertEqual(before, {path: digest(path) for path in before})
        with self.assertRaisesRegex(ValueError, "fresh output"):
            package(self.root, output)


if __name__ == "__main__":
    unittest.main()
