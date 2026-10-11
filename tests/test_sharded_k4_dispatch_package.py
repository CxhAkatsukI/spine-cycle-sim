"""Verify the frozen CPU control without a board or external run files."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import statistics
import tarfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.analysis import analyze_log
from spine_cycle_sim.experiments.sharded_k4_stages.dispatch_sweep import dispatch_metrics


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst"
PACKAGE = PARENT / "dispatch_affinity"


class DispatchPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads((PACKAGE / "dispatch_raw_index.json").read_text())
        cls.report = json.loads((PACKAGE / "dispatch.json").read_text())
        with tarfile.open(PACKAGE / "raw_dispatch.tar.gz") as stream:
            cls.members = stream.getmembers()
            cls.files = {m.name: stream.extractfile(m).read() for m in cls.members}

    def test_archive_identity_and_safe_paths(self):
        pins = {p["archive_path"]: p["sha256"] for p in self.index["files"]}
        self.assertEqual(len(pins), len(self.members))
        self.assertEqual(set(pins), set(self.files))
        for member in self.members:
            self.assertTrue(member.isfile())
            self.assertFalse(PurePosixPath(member.name).is_absolute())
            self.assertNotIn("..", PurePosixPath(member.name).parts)
            self.assertEqual(hashlib.sha256(self.files[member.name]).hexdigest(), pins[member.name])
        self.assertEqual(hashlib.sha256((PACKAGE / "raw_dispatch.tar.gz").read_bytes()).hexdigest(),
                         self.index["archive"]["sha256"])
        self.assertEqual(len(self.index["dependencies"]), 1)
        self.assertEqual(hashlib.sha256((PARENT / "empty_exit_matrix/matrix_raw_index.json").read_bytes()).hexdigest(),
                         self.index["dependencies"][0]["sha256"])

    def test_all_nine_rotating_attempts_and_no_timing_admission(self):
        saved = json.loads(self.files["summary.json"])
        manifest = json.loads(self.files["manifest.json"])
        attempts = json.loads(self.files["attempts.json"])
        self.assertEqual(attempts, saved["attempts"])
        self.assertEqual([(a["repeat"], a["arm"]) for a in attempts],
                         [(r, (r + i) % 3) for r in range(3) for i in range(3)])
        self.assertEqual(len(self.index["external_full_results"]), 9)
        self.assertEqual(len({p["sha256"] for p in self.index["external_full_results"]}), 1)
        for a in attempts:
            name = f"r{a['repeat']}_arm{a['arm']}"
            board = analyze_log(self.files[name + "/run.log"].decode(), require_trace=True)
            self.assertEqual(board, a["analysis"])
            self.assertEqual(dispatch_metrics(board), a["dispatch"])
            resources = json.loads(self.files[name + "_process.resources.json"])
            self.assertEqual(resources, a["resources"])
            self.assertEqual(resources["exit_code"], 0)
            self.assertFalse(resources["timed_out"])
            self.assertEqual(resources["command"][:3],
                             ["taskset", "--cpu-list", ",".join(map(str, manifest["affinities"][a["arm"]]))])
        for median in self.report["medians_ms"]:
            self.assertEqual(median["compute_span_ms"], statistics.median(
                a["analysis"]["compute_span_ms"] for a in attempts if a["arm"] == median["arm"]))
        for field in ("root_cause_proven", "hardware_timing_admitted", "original_A4_match_admitted",
                      "timing_fit_performed"):
            self.assertFalse(self.report[field])
        self.assertTrue(self.report["all_successors_queued_before_previous_end"])


if __name__ == "__main__":
    unittest.main()
