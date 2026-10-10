"""Check the new production-path checkpoint, independently of old A4 controls."""

import hashlib
import json
from pathlib import Path
import tarfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.analysis import analyze_log


STUDY = Path(__file__).resolve().parents[1] / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4"


class ActualK4DeliveryTests(unittest.TestCase):
    def test_raw_archive_is_complete_and_unchanged(self):
        index = json.loads((STUDY / "raw_index.json").read_text())
        path = STUDY / "raw_diagnostic.tar.gz"
        self.assertEqual(sha256_file(path), index["archive"]["sha256"])
        expected = {row["archive_path"]: row["sha256"] for row in index["files"]}
        self.assertEqual(len(expected), len(index["files"]))
        with tarfile.open(path) as archive:
            files = [member for member in archive if member.isfile()]
            self.assertEqual({member.name for member in files}, set(expected))
            for member in files:
                with archive.extractfile(member) as stream:
                    self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), expected[member.name])

    def test_all_27_logs_pass_with_matched_state_and_trace_geometry(self):
        with tarfile.open(STUDY / "raw_diagnostic.tar.gz") as archive:
            count = 0
            for folder in ("au_sssp", "au_cc", "au_respr"):
                frozen = json.load(archive.extractfile(f"{folder}/summary.json"))
                self.assertEqual(frozen["status"], "PASS")
                self.assertTrue(all(frozen["checks"].values()))
                self.assertEqual(len(frozen["attempts"]), 9)
                self.assertEqual(len({a["result"]["sha256"] for a in frozen["attempts"]}), 1)
                canonical = archive.extractfile(f"{folder}/r0_baseline/result.txt")
                self.assertEqual(hashlib.file_digest(canonical, "sha256").hexdigest(),
                                 frozen["attempts"][0]["result"]["sha256"])
                for attempt in frozen["attempts"]:
                    path = f'{folder}/r{attempt["repeat"]}_{attempt["arm"]}/run.log'
                    log = archive.extractfile(path).read().decode()
                    analysis = analyze_log(log, require_trace=attempt["arm"] == "trace_enabled")
                    self.assertEqual(analysis["result"], frozen["attempts"][0]["analysis"]["result"])
                    self.assertFalse(attempt["resources"]["timed_out"])
                    self.assertEqual(attempt["resources"]["exit_code"], 0)
                    count += 1
            self.assertEqual(count, 27)

    def test_candidate_is_not_presented_as_routed_or_final_comparison(self):
        results = json.loads((STUDY / "results.json").read_text())
        self.assertIn("optimized_routing_and_board_validation", results["not_complete"])
        self.assertIn("matched_original_A4_vs_actual_K4", results["not_complete"])
        self.assertEqual(results["synthesis"]["status"], "HLS_PASS_NOT_ROUTED")
        runs = results["synthesis"]["runs"]
        self.assertEqual(set(runs), {"original", "prefetch", "stop_after_last", "combined"})
        self.assertEqual(runs["original"]["analysis"]["resources"]["LUT"], 16952)
        self.assertEqual(runs["combined"]["analysis"]["resources"]["BRAM_18K"], 15)
        for run in runs.values():
            self.assertEqual(run["execution"]["exit_code"], 0)
            self.assertEqual(run["delivery_report_analysis"]["loops"][0]["name"], "source_loop")


if __name__ == "__main__":
    unittest.main()
