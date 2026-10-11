"""Verify shipped FPGA evidence directly from its portable raw archive."""

import hashlib
import json
from pathlib import Path
import statistics
import tarfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.analysis import analyze_log


STUDY = Path(__file__).resolve().parents[1] / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization"


class BoardDeliveryTests(unittest.TestCase):
    def test_every_archived_file_matches_frozen_index(self):
        index = json.loads((STUDY / "board_raw_index.json").read_text())
        self.assertEqual(sha256_file(STUDY / "raw_board.tar.gz"), index["archive"]["sha256"])
        expected = {row["archive_path"]: row["sha256"] for row in index["files"]}
        self.assertEqual(len(expected), len(index["files"]))
        with tarfile.open(STUDY / "raw_board.tar.gz") as archive:
            members = [member for member in archive if member.isfile()]
            self.assertEqual({member.name for member in members}, set(expected))
            for member in members:
                with archive.extractfile(member) as stream:
                    self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), expected[member.name])

    def test_all_eighteen_runs_preserve_outputs_rounds_and_reported_medians(self):
        delivered = json.loads((STUDY / "board.json").read_text())
        self.assertEqual(delivered["status"], "ROUTED_AND_PAIRED_SSSP_BOARD_PASS")
        self.assertEqual({row["case"]["case"] for row in delivered["cases"]},
                         {f"{name}_weighted_sssp_resident" for name in ("au", "su", "wk")})
        with tarfile.open(STUDY / "raw_board.tar.gz") as archive:
            for case in delivered["cases"]:
                prefix = "paired_" + case["case"]["case"].split("_")[0] + "_sssp_candidate"
                summary = json.load(archive.extractfile(prefix + "/summary.json"))
                hashes, records = set(), []
                self.assertEqual(len(summary["attempts"]), 6)
                for attempt in summary["attempts"]:
                    root = f"{prefix}/r{attempt['repeat']}_{attempt['arm']}"
                    log = archive.extractfile(root + "/run.log").read().decode()
                    analysis = analyze_log(log, require_trace=True)
                    self.assertEqual(analysis, attempt["analysis"])
                    records.append(analysis["result"])
                    hashes.add(hashlib.file_digest(archive.extractfile(root + "/result.txt"), "sha256").hexdigest())
                self.assertEqual(len(hashes), 1)
                self.assertTrue(all(row == records[0] for row in records))
                for arm in ("original", "candidate"):
                    times = [a["analysis"]["timing_ms"]["setup_inclusive_ms"]
                             for a in summary["attempts"] if a["arm"] == arm]
                    self.assertEqual(statistics.median(times), case["medians"][arm]["setup_inclusive_ms"])
                self.assertEqual(case["old_over_new"]["setup_inclusive_ms"],
                                 case["medians"]["original"]["setup_inclusive_ms"] /
                                 case["medians"]["candidate"]["setup_inclusive_ms"])

    def test_monitoring_gap_and_remaining_work_are_explicit(self):
        result = json.loads((STUDY / "board.json").read_text())
        recovery = result["admission"]["link_recovery"]
        self.assertIsNone(recovery["process_exit_code"])
        self.assertFalse(recovery["continuous_resource_monitoring_verified"])
        self.assertTrue(recovery["vendor_duration_exceeded_configured_timeout"])
        for item in ("optimized_production_simulator", "matched_original_A4_vs_actual_K4", "publication_speed_match"):
            self.assertIn(item, result["not_complete"])


if __name__ == "__main__":
    unittest.main()
