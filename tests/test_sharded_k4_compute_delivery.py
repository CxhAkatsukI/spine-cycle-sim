"""Portable replay checks for compute extraction and finite shared ports."""

import hashlib
import json
from pathlib import Path
import tarfile
import unittest
import subprocess
import sys

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.compute_delivery import package_model_compute


STUDY = Path(__file__).resolve().parents[1] / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/compute_ports"


class ComputeDeliveryTests(unittest.TestCase):
    def test_frozen_package_cannot_be_overwritten(self):
        with self.assertRaises(FileExistsError):
            package_model_compute(Path("unused"), Path("unused"), STUDY)

    def test_cli_rejects_mixed_evidence_classes(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([
            sys.executable, str(root / "scripts/package_sharded_k4_adapter_gates.py"),
            "--data", "unused", "--integration", "unused", "--output", "unused",
            "--model-adapter", "--model-compute",
        ], cwd=root, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("require separate packages", result.stderr)

    def test_archive_members_match_index(self):
        index = json.loads((STUDY / "compute_raw_index.json").read_text())
        path = STUDY / "raw_compute_ports.tar.gz"
        self.assertEqual(sha256_file(path), index["archive"]["sha256"])
        expected = {row["archive_path"]: row["sha256"] for row in index["files"]}
        self.assertEqual(len(expected), len(index["files"]))
        with tarfile.open(path) as archive:
            members = [member for member in archive if member.isfile()]
            self.assertEqual({member.name for member in members}, set(expected))
            for member in members:
                self.assertEqual(hashlib.file_digest(archive.extractfile(member), "sha256").hexdigest(), expected[member.name])

    def test_both_regressions_preserve_all_result_bytes(self):
        result = json.loads((STUDY / "compute_ports.json").read_text())
        self.assertEqual(set(result["legacy"]), {"extracted", "shared", "shared_final"})
        with tarfile.open(STUDY / "raw_compute_ports.tar.gz") as archive:
            for phase, comparison in result["legacy"].items():
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
            core = json.load(archive.extractfile("final_core_gate_identity.json"))
            final = json.load(archive.extractfile("shared_final/identity.json"))
            self.assertEqual(core["source"], final["source"])
            self.assertEqual(len(core["executables"]), 2)
            self.assertEqual(len(core["test_sources"]), 2)
            for pin in core["source"]["files"]:
                self.assertEqual(hashlib.file_digest(archive.extractfile("source/" + pin["path"]), "sha256").hexdigest(),
                                 pin["sha256"])

    def test_component_counts_and_failed_attempts_are_retained(self):
        with tarfile.open(STUDY / "raw_compute_ports.tar.gz") as archive:
            for name, expected in (
                ("final_shared_axi_test", "PASS: 72 shared-master pressure/order/conservation cases"),
                ("final_connected_compute_test", "PASS: 25 connected Apply/writeback full-state and traffic cases"),
            ):
                self.assertEqual(archive.extractfile(name + ".stdout.txt").read().decode().strip(), expected)
                resource = json.load(archive.extractfile(name + ".resources.json"))
                self.assertEqual(resource["exit_code"], 0)
                self.assertFalse(resource["timed_out"])
            report = archive.extractfile("final_core_ctest.stdout.txt").read().decode()
            self.assertIn("100% tests passed, 0 tests failed out of 18", report)
            self.assertNotEqual(json.load(archive.extractfile("core_build.resources.json"))["exit_code"], 0)
            failed = archive.extractfile("connected_first_ctest.stdout.txt").read().decode()
            self.assertIn("connected backend did not use the declared number of masters", failed)

    def test_not_a_system_or_hardware_timing_claim(self):
        result = json.loads((STUDY / "compute_ports.json").read_text())
        self.assertEqual(result["status"], "LEGACY_EQUIVALENCE_AND_SHARED_COMPUTE_PORT_PASS")
        self.assertEqual(result["component_cases"], {"shared_axi": 72, "connected_compute": 25, "ctest_executables": 18})
        for gate in ("production_candidate_scatter_and_pairwise_source_service",
                     "independent_adapter_gather_dispatch_and_ordered_mux",
                     "one_round_shared_apply_hbm_lifetime_and_status_write",
                     "distinct_candidate_profile_and_complete_system_gates",
                     "matched_hardware_component_and_system_timing",
                     "matched_original_A4_vs_actual_K4", "publication_speed_match"):
            self.assertIn(gate, result["remaining"])


if __name__ == "__main__":
    unittest.main()
