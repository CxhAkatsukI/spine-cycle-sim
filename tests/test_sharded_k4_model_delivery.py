"""Recheck portable adapter and legacy-preservation evidence without FPGA/Vitis."""

import hashlib
import json
from pathlib import Path
import tarfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.model_adapter import require_case_report


STUDY = Path(__file__).resolve().parents[1] / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync"


class ModelDeliveryTests(unittest.TestCase):
    def test_archive_and_all_members_match_index(self):
        index = json.loads((STUDY / "model_raw_index.json").read_text())
        self.assertEqual(sha256_file(STUDY / "raw_model_adapter.tar.gz"), index["archive"]["sha256"])
        expected = {row["archive_path"]: row["sha256"] for row in index["files"]}
        self.assertEqual(len(expected), len(index["files"]))
        with tarfile.open(STUDY / "raw_model_adapter.tar.gz") as archive:
            members = [member for member in archive if member.isfile()]
            self.assertEqual({member.name for member in members}, set(expected))
            for member in members:
                self.assertEqual(hashlib.file_digest(archive.extractfile(member), "sha256").hexdigest(), expected[member.name])

    def test_each_legacy_checkpoint_preserves_all_result_bytes(self):
        delivered = json.loads((STUDY / "model_adapter.json").read_text())
        self.assertEqual(set(delivered["legacy"]), {"extracted", "candidate", "candidate_final"})
        with tarfile.open(STUDY / "raw_model_adapter.tar.gz") as archive:
            for phase, comparison in delivered["legacy"].items():
                self.assertEqual(comparison["status"], "PASS")
                self.assertEqual(comparison["correctness_admitted_cases"], 5)
                self.assertEqual(comparison["ignored_result_fields"], [])
                for row in comparison["cases"]:
                    path = f"cases/{row['case']}/result.json"
                    before = archive.extractfile("before/" + path).read()
                    after = archive.extractfile(phase + "/" + path).read()
                    self.assertEqual(before, after)
                    self.assertTrue(json.loads(after)["success"])
                    self.assertEqual(hashlib.sha256(after).hexdigest(), row["result_hashes"][1])

    def test_raw_component_reports_and_failed_attempts_remain_visible(self):
        with tarfile.open(STUDY / "raw_model_adapter.tar.gz") as archive:
            prefix = "shared_fixture_completion/"
            summary = json.load(archive.extractfile(prefix + "summary.json"))
            self.assertEqual(len(summary["attempts"]), 25)
            hls_cases = 0
            for attempt in summary["attempts"]:
                self.assertEqual(attempt["resources"]["exit_code"], 0)
                name = attempt["name"]
                if name == "cycle_model" or name.endswith("_run"):
                    report = archive.extractfile(prefix + name + ".stdout.txt").read().decode()
                    count = require_case_report(report, hls=name != "cycle_model")
                    if name.endswith("_run"):
                        hls_cases += count
            self.assertEqual(hls_cases, 324)
            failed = json.load(archive.extractfile("empty_notice_before_fix.resources.json"))
            self.assertEqual(failed["exit_code"], 1)
            stderr = archive.extractfile("empty_notice_before_fix.stderr.txt").read().decode()
            self.assertIn("empty stream completion did not wake", stderr)
            link = json.load(archive.extractfile("shared_fixture_hls/weighted_prefetch0_stop0_build.resources.json"))
            self.assertNotEqual(link["exit_code"], 0)

    def test_no_system_timing_or_publication_claim(self):
        result = json.loads((STUDY / "model_adapter.json").read_text())
        self.assertEqual(result["status"], "LEGACY_EQUIVALENCE_AND_ADAPTER_FUNCTIONAL_PASS")
        for gate in ("production_candidate_scatter_and_completion_wiring",
                     "independent_frontend_dispatch_and_shared_round_backend",
                     "matched_hardware_component_and_system_timing",
                     "matched_original_A4_vs_actual_K4", "publication_speed_match"):
            self.assertIn(gate, result["remaining"])


if __name__ == "__main__":
    unittest.main()
