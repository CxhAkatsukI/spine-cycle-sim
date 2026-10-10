"""Verify the frozen pre-route checkpoint without requiring external tools."""

import hashlib
import json
from pathlib import Path
import tarfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file


STUDY = Path(__file__).resolve().parents[1] / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization"


class AdapterGateDeliveryTests(unittest.TestCase):
    def test_raw_archive_and_every_member_match_index(self):
        index = json.loads((STUDY / "pre_route_raw_index.json").read_text())
        path = STUDY / "raw_pre_route.tar.gz"
        self.assertEqual(sha256_file(path), index["archive"]["sha256"])
        expected = {row["archive_path"]: row["sha256"] for row in index["files"]}
        self.assertEqual(len(expected), len(index["files"]))
        with tarfile.open(path) as archive:
            members = [member for member in archive if member.isfile()]
            self.assertEqual({member.name for member in members}, set(expected))
            for member in members:
                with archive.extractfile(member) as stream:
                    self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), expected[member.name])

    def test_all_six_rtl_runs_and_four_failed_attempts_are_retained(self):
        results = json.loads((STUDY / "pre_route.json").read_text())
        with tarfile.open(STUDY / "raw_pre_route.tar.gz") as archive:
            for mode in ("weighted", "destination", "unit"):
                for variant in ("original", "combined"):
                    root = f"rtl_{mode}_safe_index/{variant}"
                    log = archive.extractfile(root + "/cosim.stdout.txt").read().decode()
                    self.assertEqual(log.count("PMA_COSIM_RESULT status=PASS cases=13 packets=200"), 3)
                    self.assertIn("C/RTL co-simulation finished: PASS", log)
                    run = results["rtl"][mode]["runs"][variant]
                    self.assertEqual(run["execution"]["exit_code"], 0)
                    self.assertFalse(run["execution"]["timed_out"])
            for name, failure in results["retained_failures"].items():
                self.assertNotEqual(failure["exit_code"], 0)
                log = archive.extractfile(name + "/original/cosim.stdout.txt").read().decode()
                self.assertIn("ERROR", log)
            self.assertEqual(len(results["retained_failures"]), 4)

    def test_gate_admission_is_not_reported_as_optimized_hardware(self):
        results = json.loads((STUDY / "pre_route.json").read_text())
        self.assertEqual(results["status"], "SOURCE_RTL_HLS_AND_OLD_BOARD_REGRESSION_PASS_NOT_OPTIMIZED_FPGA")
        self.assertIn("optimized_routing_and_board_validation", results["not_complete"])
        self.assertIn("optimized_production_simulator", results["not_complete"])
        self.assertIn("matched_original_A4_vs_actual_K4", results["not_complete"])
        self.assertEqual(set(results["synthesis"]["runs"]), {"original", "prefetch", "stop_after_last", "combined"})
        for run in results["synthesis"]["runs"].values():
            self.assertEqual(run["execution"]["exit_code"], 0)
        regression = results["board_helper_regression"]
        self.assertTrue(all(regression["checks"].values()))
        self.assertEqual(len(regression["attempts"]), 3)
        self.assertEqual(len({attempt["result"]["sha256"] for attempt in regression["attempts"]}), 1)


if __name__ == "__main__":
    unittest.main()
