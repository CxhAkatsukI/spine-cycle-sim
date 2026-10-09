import copy
import json
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.original_regraph_validation.big.analysis import (
    analyze_tests, analyze_comparison,
)
from spine_cycle_sim.experiments.original_regraph_validation.big.study import source_identities

ROOT = Path(__file__).resolve().parents[1]


class BigAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / "configs/experiments/original_regraph_big_gather_validation_v1.json").read_text())
        self.config = {"clock_mhz": 210, "big": 3, "big_vertices": 524288, "bank_rows": 32768,
                       "forwarding_entries": 4, "timing": copy.deepcopy(self.contract["timing"])}
        self.rejections = {"port_and_lifecycle_checks": 8, "wrong_bank": True}
        self.rows = [{"id": name, "cycles": 100, "output_stalls": 0, "capacity_stalls": 0, "checked_words": 524288}
                     for name in self.contract["cases"]]
        for index in (5, 6):
            self.rows[index].update(cycles=200, output_stalls=10, capacity_stalls=10)

    def text(self):
        return "\n".join(["BIG_CONFIG " + json.dumps(self.config), "BIG_REJECTIONS " + json.dumps(self.rejections),
                          *("BIG_CASE " + json.dumps(row) for row in self.rows)])

    def test_fixed_model_and_finite_matrix_admitted(self):
        self.assertEqual(analyze_tests(self.text(), self.contract), self.rows)

    def test_missing_duplicate_reordered_or_untyped_rows_rejected(self):
        original = copy.deepcopy(self.rows)
        for rows in (original[:-1], original + original[:1], list(reversed(original))):
            self.rows = rows
            with self.assertRaises(ValueError): analyze_tests(self.text(), self.contract)
        for key, value in (("cycles", True), ("checked_words", 524288.0), ("output_stalls", -1), ("capacity_stalls", False)):
            self.rows = copy.deepcopy(original)
            self.rows[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): analyze_tests(self.text(), self.contract)

    def test_timing_geometry_and_rejection_records_are_required(self):
        self.config["timing"]["merge"]["latency"] = 1
        with self.assertRaisesRegex(ValueError, "timing/geometry"): analyze_tests(self.text(), self.contract)
        self.config["timing"] = self.contract["timing"]
        self.rejections["wrong_bank"] = 1
        with self.assertRaisesRegex(ValueError, "rejection gates"): analyze_tests(self.text(), self.contract)

    def test_reverse_and_repeat_must_preserve_every_counter(self):
        for index in (1, 3):
            self.rows[index]["output_stalls"] = 2
            with self.assertRaisesRegex(ValueError, "reversal/reuse"): analyze_tests(self.text(), self.contract)
            self.rows[index]["output_stalls"] = 0

    def test_capacity_and_backpressure_must_change_runtime(self):
        for index in (5, 6):
            self.rows[index]["cycles"] = 100
            with self.assertRaisesRegex(ValueError, "finite pressure"): analyze_tests(self.text(), self.contract)
            self.rows[index]["cycles"] = 200

    def test_source_comparison_checks_extent_order_and_repeat(self):
        rows = [{"case": case, "cycles": 100, "checked_words": 524288, "output_stalls": 0, "capacity_stalls": 0}
                for case in self.contract["source_case_order"]]
        def text(): return "\n".join("BIG_COMPARISON " + json.dumps(row) for row in rows)
        self.assertEqual(analyze_comparison(text(), self.contract), rows)
        rows[-1]["cycles"] = 101
        with self.assertRaisesRegex(ValueError, "reuse"): analyze_comparison(text(), self.contract)
        rows[-1]["cycles"] = 100
        rows[0]["checked_words"] -= 1
        with self.assertRaisesRegex(ValueError, "extent"): analyze_comparison(text(), self.contract)

    def test_source_identity_contains_routing_banks_and_study(self):
        paths = {row["path"] for row in source_identities(ROOT)}
        for name in ("cpp/src/original_regraph/big_routing.cpp", "cpp/src/original_regraph/big_gather.cpp",
                     "cpp/src/original_regraph/big_merge.cpp", "cpp/tests/publication_sources/regraph_big_gather_probe.cpp",
                     "spine_cycle_sim/experiments/original_regraph_validation/big/study.py"):
            self.assertIn(name, paths)


if __name__ == "__main__":
    unittest.main()
