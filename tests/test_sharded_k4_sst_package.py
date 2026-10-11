"""Portable checks for the frozen SST checkpoint, without external tool roots."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst"


def digest(stream):
    value = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        value.update(chunk)
    return value.hexdigest()


class FrozenSstPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((PACKAGE / "sst.json").read_text())
        cls.index = json.loads((PACKAGE / "sst_raw_index.json").read_text())
        cls.pins = {item["archive_path"]: item["sha256"] for item in cls.index["files"]}

    def test_functional_pass_does_not_admit_timing_or_a4(self):
        report = self.report
        self.assertEqual(report["status"], "SSSP_SST_FUNCTIONAL_PASS_TIMING_MISMATCH_RETAINED")
        self.assertFalse(report["hardware_timing_admitted"])
        self.assertFalse(report["original_A4_match_admitted"])
        self.assertEqual({row["id"] for row in report["rows"]},
                         {f"{case}_{arm}" for case in ("au", "su", "wk") for arm in ("original", "candidate")})
        self.assertEqual(len(report["rows"]), 6)
        for row in report["rows"]:
            self.assertTrue(row["result"]["success"])
            self.assertTrue(row["result"]["ledger_closed"])
            self.assertTrue(row["result"]["replicas_equal"])
            self.assertEqual(row["result"]["mismatches"], 0)
            self.assertFalse(row["timing"]["hardware_timing_admitted"])
        self.assertEqual(report["legacy"]["status"], "PASS")
        self.assertEqual(report["legacy"]["correctness_admitted_cases"], 5)
        self.assertFalse(report["legacy"]["ignored_result_fields"])

    def test_every_archive_member_matches_frozen_index(self):
        self.assertEqual(len(self.pins), len(self.index["files"]))
        with (PACKAGE / "raw_sst.tar.gz").open("rb") as stream:
            self.assertEqual(digest(stream), self.index["archive"]["sha256"])
        found = set()
        with tarfile.open(PACKAGE / "raw_sst.tar.gz", "r|gz") as archive:
            for member in archive:
                with self.subTest(path=member.name):
                    path = PurePosixPath(member.name)
                    self.assertFalse(path.is_absolute())
                    self.assertNotIn("..", path.parts)
                    self.assertTrue(member.isfile())
                    self.assertNotIn(member.name, found)
                    self.assertIn(member.name, self.pins)
                    found.add(member.name)
                    self.assertEqual(digest(archive.extractfile(member)), self.pins[member.name])
        self.assertEqual(found, set(self.pins))

    def test_complete_board_bytes_and_one_fixture_per_graph(self):
        for row in self.report["rows"]:
            name = row["id"]
            self.assertEqual(self.pins[f"campaign/matrix_final/{name}/result.json.values.txt"],
                             self.pins[f"board/{name}/result.txt"])
        for row in self.report["input_audits"]["rows"]:
            self.assertEqual(row["audit"]["status"], "PASS")
            self.assertEqual(row["audit"]["old_state_mismatches"], 0)
            self.assertEqual(self.pins[f"fixtures/{row['id']}.bin"], row["fixture"]["sha256"])
        self.assertEqual(len([path for path in self.pins if path.startswith("fixtures/")]), 3)

    def test_common_numerical_source_and_plugin(self):
        expected = self.report["legacy"]["candidate_identity"]
        paths = {f"campaign/matrix_final/{row['id']}/manifest.json" for row in self.report["rows"]}
        found = set()
        with tarfile.open(PACKAGE / "raw_sst.tar.gz", "r|gz") as archive:
            for member in archive:
                if member.name in paths:
                    manifest = json.load(archive.extractfile(member))
                    self.assertEqual(manifest["source"], expected["source"])
                    self.assertEqual(manifest["plugin"]["plugin_sha256"], expected["plugin_sha256"])
                    found.add(member.name)
        self.assertEqual(found, paths)
        self.assertEqual(self.pins["binaries/libspine_cycle.so"], expected["plugin_sha256"])


if __name__ == "__main__":
    unittest.main()
