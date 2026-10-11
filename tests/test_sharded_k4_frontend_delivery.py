"""Portable integrity and scope checks for the frozen frontend checkpoint."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
import io

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.frontend_delivery import package_model_frontend
from spine_cycle_sim.experiments.sharded_k4_stages.model_frontend import REPORTS

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/frontend"


class FrontendDelivery(unittest.TestCase):
    def test_frozen_package_cannot_be_overwritten(self):
        with self.assertRaises(FileExistsError):
            package_model_frontend(Path("unused"), Path("unused"), STUDY)

    def test_cli_does_not_mix_checkpoints(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/package_sharded_k4_adapter_gates.py"),
            "--data", "unused", "--integration", "unused", "--output", "unused",
            "--model-compute", "--model-frontend"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("require separate packages", result.stderr)

    def test_every_archive_member_matches_index(self):
        index = json.loads((STUDY / "frontend_raw_index.json").read_text())
        archive_path = STUDY / "raw_frontend.tar.gz"
        self.assertEqual(sha256_file(archive_path), index["archive"]["sha256"])
        expected = {row["archive_path"]: row["sha256"] for row in index["files"]}
        self.assertEqual(len(expected), len(index["files"]))
        with tarfile.open(archive_path) as archive:
            members = [member for member in archive if member.isfile()]
            self.assertEqual({member.name for member in members}, set(expected))
            for member in members:
                self.assertEqual(hashlib.file_digest(archive.extractfile(member), "sha256").hexdigest(), expected[member.name])

    def test_complete_legacy_bytes_and_source_identity(self):
        result = json.loads((STUDY / "frontend.json").read_text())
        comparison = result["legacy"]
        self.assertEqual(comparison["status"], "PASS")
        self.assertEqual(comparison["correctness_admitted_cases"], 5)
        self.assertEqual(comparison["ignored_result_fields"], [])
        with tarfile.open(STUDY / "raw_frontend.tar.gz") as archive:
            for case in comparison["cases"]:
                suffix = f"cases/{case['case']}/result.json"
                self.assertEqual(archive.extractfile("before/" + suffix).read(),
                                 archive.extractfile("legacy_final/" + suffix).read())
            core = json.load(archive.extractfile("final_core_gate_identity.json"))
            final = json.load(archive.extractfile("legacy_final/identity.json"))
            self.assertEqual(core["source"], final["source"])
            for pin in final["source"]["files"]:
                self.assertEqual(hashlib.file_digest(archive.extractfile("source/simulator/" + pin["path"]), "sha256").hexdigest(),
                                 pin["sha256"])

    def test_measured_xo_not_replaced_by_current_source(self):
        result = json.loads((STUDY / "frontend.json").read_text())
        self.assertEqual(result["frontend"]["reports"], REPORTS)
        self.assertIn("matched_hardware_timing", result["remaining"])
        artifact = result["frontend"]["hardware_artifact"]
        with tarfile.open(STUDY / "raw_frontend.tar.gz") as archive:
            xo = archive.extractfile("source/external/" + artifact["xo"]["path"].lstrip("/")).read()
            self.assertEqual(hashlib.sha256(xo).hexdigest(), artifact["xo"]["sha256"])
            with zipfile.ZipFile(io.BytesIO(xo)) as package:
                xml = ET.fromstring(package.read("kernelHBMWrapper/kernel.xml"))
                masters = sorted(port.attrib["name"] for port in xml.iter("port") if port.attrib.get("mode") == "master")
                self.assertEqual(masters, [f"M_AXI_GMEM{i}" for i in range(1, 5)])
            self.assertNotEqual(artifact["embedded_source"]["sha256"],
                                "04041f066fd1bf99802cc668b4d583da9104b25bdf1b4125dda00ca2963ffd0d")
            for name in ("source_test", "scatter_build", "scatter_debug"):
                self.assertNotEqual(json.load(archive.extractfile(name + ".resources.json"))["exit_code"], 0)
            self.assertIn("depth-one deadlock", result["frontend"]["reports"]["scatter"])


if __name__ == "__main__":
    unittest.main()
