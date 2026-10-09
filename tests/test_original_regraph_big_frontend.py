import copy
import json
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.original_regraph_validation.big.frontend_analysis import analyze
from spine_cycle_sim.experiments.original_regraph_validation.big.frontend_study import identities

ROOT = Path(__file__).resolve().parents[1]


class BigFrontendAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / "configs/experiments/original_regraph_big_frontend_validation_v1.json").read_text())
        self.rows = [{"id": name, "cycles": 100, "logical_requests": 10, "reads": 4, "cache_hits": 6,
                      "edge_bytes": 4096, "source_bytes": 256, "capacity_stalls": 0, "response_stalls": 0,
                      "scatter_stalls": 0, "fork_stalls": 0, "checked_tuples": 512} for name in self.contract["cases"]]
        for index in (3, 6): self.rows[index].update(reads=1, logical_requests=1, cache_hits=0, source_bytes=64)
        for index in (8, 9, 10, 11): self.rows[index]["cycles"] = 200
        self.rows[10]["capacity_stalls"] = 1
        self.rows[11].update(scatter_stalls=1, fork_stalls=1)

    def text(self):
        return "\n".join(["BIG_FRONTEND_REJECTIONS {\"checks\":8}", *(
            "BIG_FRONTEND " + json.dumps(row) for row in self.rows)])

    def test_fixed_finite_matrix(self):
        self.assertEqual(analyze(self.text(), self.contract), self.rows)

    def test_missing_reordered_duplicate_and_untyped_fields(self):
        original = copy.deepcopy(self.rows)
        for rows in (original[:-1], original + original[:1], list(reversed(original))):
            self.rows = rows
            with self.assertRaises(ValueError): analyze(self.text(), self.contract)
        for key, value in (("cycles", True), ("checked_tuples", 512.0), ("cache_hits", False), ("reads", -1)):
            self.rows = copy.deepcopy(original); self.rows[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): analyze(self.text(), self.contract)

    def test_cache_hit_must_not_be_counted_as_memory_read(self):
        self.rows[0]["reads"] = 10
        self.rows[0]["source_bytes"] = 640
        with self.assertRaisesRegex(ValueError, "cache/byte"): analyze(self.text(), self.contract)

    def test_reverse_and_reuse_require_all_counters(self):
        for index in (1, 2):
            self.rows[index]["response_stalls"] = 1
            with self.assertRaisesRegex(ValueError, "reversal/reuse"): analyze(self.text(), self.contract)
            self.rows[index]["response_stalls"] = 0

    def test_credit_and_latency_controls_required(self):
        for index in (8, 9, 10, 11):
            self.rows[index]["cycles"] = 100
            with self.assertRaisesRegex(ValueError, "finite memory"): analyze(self.text(), self.contract)
            self.rows[index]["cycles"] = 200

    def test_source_comparison_requires_every_request_response_and_tuple(self):
        self.rows = [dict(self.rows[0], id=f"source_case{id}", checked_tuples=bursts * 8, edge_bytes=bursts * 64)
                     for id, bursts in zip(self.contract["source_cases"], self.contract["source_bursts"], strict=True)]
        summary = {"cases": 6, "requests": 66, "response_words": 1056, "tuple_words": 4240}
        text = self.text() + "\nBIG_FRONTEND_COMPARISON " + json.dumps(summary)
        self.assertEqual(analyze(text, self.contract, True), self.rows)
        with self.assertRaisesRegex(ValueError, "comparison incomplete"):
            analyze(text.replace('"requests": 66', '"requests": 65'), self.contract, True)

    def test_identity_covers_new_code_and_actual_author_probe(self):
        paths = {item["path"] for item in identities(ROOT)}
        for path in ("cpp/src/original_regraph/big_source_memory.cpp", "cpp/src/original_regraph/big_requests.cpp",
                     "cpp/src/original_regraph/big_scatter.cpp", "cpp/tests/publication_sources/regraph_big_frontend_probe.cpp",
                     "scripts/run_original_regraph_big_frontend_validation.py"):
            self.assertIn(path, paths)


if __name__ == "__main__": unittest.main()
