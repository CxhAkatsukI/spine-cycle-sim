"""Portable integrity checks for the complete candidate and unchanged legacy evidence."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.system_delivery import package_model_system
from spine_cycle_sim.experiments.sharded_k4_stages.model_system import require_system_report

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/system"


class SystemDelivery(unittest.TestCase):
    def test_immutable(self):
        with self.assertRaises(FileExistsError): package_model_system(Path("unused"), Path("unused"), STUDY)

    def test_cli_separates_evidence(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/package_sharded_k4_adapter_gates.py"),
            "--data", "unused", "--integration", "unused", "--output", "unused",
            "--model-system", "--model-frontend"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("require separate packages", result.stderr)

    def test_archive_integrity(self):
        index = json.loads((STUDY / "system_raw_index.json").read_text())
        path = STUDY / "raw_system.tar.gz"
        self.assertEqual(sha256_file(path), index["archive"]["sha256"])
        expected = {row["archive_path"]: row["sha256"] for row in index["files"]}
        self.assertEqual(len(expected), len(index["files"]))
        with tarfile.open(path) as archive:
            members = [member for member in archive if member.isfile()]
            self.assertEqual({member.name for member in members}, set(expected))
            for member in members:
                self.assertEqual(hashlib.file_digest(archive.extractfile(member), "sha256").hexdigest(), expected[member.name])

    def test_complete_gate_and_scope(self):
        result = json.loads((STUDY / "system.json").read_text())
        gate = result["system"]
        self.assertEqual((gate["converged_executions"], gate["fixed_round_executions"], gate["expected_limit_failures"]), (11, 1, 1))
        self.assertFalse(gate["sst_candidate_profile_selected"])
        self.assertIn("matched_FPGA_timing", result["remaining"])
        with tarfile.open(STUDY / "raw_system.tar.gz") as archive:
            rows = require_system_report(archive.extractfile("system_final/system.stdout.txt").read().decode())
            self.assertEqual(rows, gate["rows"])
            self.assertIn("whole routed system timed out", archive.extractfile("system_attempt_1.stderr.txt").read().decode())
            self.assertIn("pre_domain_checkpoint.tar.gz", archive.getnames())

    def test_exact_legacy_and_source_binding(self):
        result = json.loads((STUDY / "system.json").read_text())
        self.assertEqual(result["legacy"]["correctness_admitted_cases"], 5)
        self.assertEqual(result["legacy"]["ignored_result_fields"], [])
        with tarfile.open(STUDY / "raw_system.tar.gz") as archive:
            final = json.load(archive.extractfile("legacy_final/identity.json"))
            self.assertEqual(final["source"], result["system"]["source"])
            for case in result["legacy"]["cases"]:
                suffix = "cases/" + case["case"] + "/result.json"
                self.assertEqual(archive.extractfile("before/" + suffix).read(), archive.extractfile("legacy_final/" + suffix).read())
            for pin in final["source"]["files"]:
                self.assertEqual(hashlib.file_digest(archive.extractfile("source/simulator/" + pin["path"]), "sha256").hexdigest(), pin["sha256"])


if __name__ == "__main__":
    unittest.main()
