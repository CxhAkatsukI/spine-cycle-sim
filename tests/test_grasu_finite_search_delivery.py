import hashlib
import json
from pathlib import Path
import tarfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.finite_search.analysis import analyze


ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/search_pipeline/finite_model"


class FiniteSearchDeliveryTests(unittest.TestCase):
    def check_archive(self, directory, name, members):
        with tarfile.open(directory / name) as archive:
            self.assertEqual(sorted(archive.getnames()), sorted(row["member"] for row in members))
            for row in members:
                content = archive.extractfile(row["member"]).read()
                self.assertEqual(len(content), row["bytes"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), row["sha256"])

    def test_complete_matrix_and_raw_evidence(self):
        directory = DELIVERY / "evidence"
        index = json.loads((directory / "index.json").read_text())
        for row in index["reports"]:
            path = directory / row["file"]
            self.assertEqual(sha256_file(path), row["sha256"])
            self.assertEqual(path.stat().st_size, row["bytes"])
        matrix = json.loads((directory / "matrix.json").read_text())
        previous = json.loads((directory / "previous_metadata.json").read_text())
        summary = analyze(matrix, previous)
        self.assertEqual(index["prediction_rows"], 228)
        self.assertEqual(summary["exact_replayed_rows"], 190)
        self.assertEqual(len(summary["comparisons"]), 38)
        self.assertTrue(summary["within_ten_percent_both_directions"])
        for key, value in summary.items():
            self.assertEqual(index[key], value)
        for field in ("baseline_admitted", "hardware_timing_admitted",
                "publication_match_admitted", "new_spine_comparison_executed"):
            self.assertFalse(index[field])
        self.check_archive(directory, "raw_runs.tar.gz", index["raw_members"])

    def test_regressions_keep_failed_attempts_and_default_only_sst_scope(self):
        directory = DELIVERY / "verification"
        index = json.loads((directory / "index.json").read_text())
        archive = directory / index["archive"]["file"]
        self.assertEqual(sha256_file(archive), index["archive"]["sha256"])
        self.assertEqual(archive.stat().st_size, index["archive"]["bytes"])
        self.assertEqual(index["core_tests"], 31)
        self.assertEqual(index["focused_python_tests"], 95)
        self.assertEqual(len(index["sst_exact_default_smokes"]), 2)
        self.assertEqual(len(index["checks"]), 14)
        for row in index["checks"]:
            self.assertEqual(row["exit_code"], row["expected_exit_code"])
            self.assertFalse(row["timed_out"])
            self.assertGreater(row["memory_limit_gib"], 0)
            self.assertLessEqual(row["memory_limit_gib"], 2)
            self.assertGreaterEqual(row["reserve_gib"], 8)
        self.assertEqual([row["exit_code"] for row in index["checks"] if row["exit_code"]], [2, 8])
        for field in ("baseline_admitted", "hardware_timing_admitted", "publication_match_admitted",
                "candidate_sst_timing_admitted", "new_spine_comparison_executed"):
            self.assertFalse(index[field])
        self.check_archive(directory, "regressions.tar.gz", index["members"])


if __name__ == "__main__":
    unittest.main()
