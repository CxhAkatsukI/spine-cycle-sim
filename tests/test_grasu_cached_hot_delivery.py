import hashlib
import json
from pathlib import Path
import tarfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.cached_hot.analysis import analyze


ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/cached_hot"


class CachedHotDeliveryTests(unittest.TestCase):
    def check_archive(self, directory, name, members):
        path = directory / name
        with tarfile.open(path) as archive:
            self.assertEqual(sorted(archive.getnames()), sorted(r["member"] for r in members))
            for row in members:
                content = archive.extractfile(row["member"]).read()
                self.assertEqual(len(content), row["bytes"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), row["sha256"])

    def test_matrix_and_archived_runs(self):
        directory = DELIVERY / "evidence"
        index = json.loads((directory / "index.json").read_text())
        for row in index["reports"]:
            path = directory / row["file"]
            self.assertEqual(sha256_file(path), row["sha256"])
            self.assertEqual(path.stat().st_size, row["bytes"])
        matrix = json.loads((directory / "matrix.json").read_text())
        previous = json.loads((directory / "previous_hot_owners.json").read_text())
        summary = analyze(matrix, previous)
        self.assertEqual(summary["old_checkpoint_exact_rows"], 152)
        self.assertFalse(summary["legacy_reference_no_more_than_ten_percent_slower"])
        for key, value in summary.items():
            self.assertEqual(index[key], value)
        self.assertFalse(index["baseline_admitted"])
        self.check_archive(directory, "raw_runs.tar.gz", index["raw_members"])

    def test_regressions_and_failures_are_preserved(self):
        directory = DELIVERY / "verification"
        index = json.loads((directory / "index.json").read_text())
        self.assertEqual(sha256_file(directory / index["archive"]["file"]), index["archive"]["sha256"])
        self.assertEqual(index["core_tests"], 30)
        self.assertEqual(index["failed_analyzer_attempt_exact_replay_rows"], 190)
        self.assertEqual(index["historical_identity"]["current_mismatched_subassertions"], 27)
        self.assertFalse(index["historical_identity"]["suite_reported_green"])
        self.assertFalse(index["baseline_admitted"])
        self.assertFalse(index["candidate_sst_timing_admitted"])
        for row in index["checks"]:
            self.assertEqual(row["exit_code"], row["expected_exit_code"])
            self.assertFalse(row["timed_out"])
        self.assertEqual([r["expected_exit_code"] for r in index["checks"] if r["expected_exit_code"]], [8, 1, 1])
        self.check_archive(directory, "regressions.tar.gz", index["members"])


if __name__ == "__main__":
    unittest.main()
