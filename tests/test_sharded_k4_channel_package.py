"""Portable integrity and evidence-boundary checks for the channel checkpoint."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst"
PACKAGE = PARENT / "independent_channels"


def digest(stream):
    value = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        value.update(chunk)
    return value.hexdigest()


class FrozenChannelPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((PACKAGE / "channels.json").read_text())
        cls.index = json.loads((PACKAGE / "channels_raw_index.json").read_text())
        cls.pins = {item["archive_path"]: item["sha256"] for item in cls.index["files"]}
        cls.parent = json.loads((PARENT / "sst_raw_index.json").read_text())
        cls.parent_pins = {item["archive_path"]: item["sha256"] for item in cls.parent["files"]}
        cls.archive = tempfile.TemporaryFile()
        cls.addClassCleanup(cls.archive.close)
        parts = sorted(PACKAGE.glob("raw_channels.tar.gz.part*"))
        if [path.name for path in parts] != [f"raw_channels.tar.gz.part{i:02d}" for i in range(3)]:
            raise ValueError("all three ordered archive volumes are required")
        for path in parts:
            with path.open("rb") as stream:
                shutil.copyfileobj(stream, cls.archive)
        cls.archive.seek(0)
        if digest(cls.archive) != cls.index["archive"]["sha256"]:
            raise ValueError("assembled archive differs from the frozen identity")

    @classmethod
    def open_archive(cls):
        cls.archive.seek(0)
        return tarfile.open(fileobj=cls.archive, mode="r|gz")

    def test_complete_matrix_is_not_timing_or_a4_admission(self):
        report = self.report
        self.assertEqual(report["status"], "INDEPENDENT_CHANNELS_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC")
        self.assertFalse(report["hardware_timing_admitted"])
        self.assertFalse(report["original_A4_match_admitted"])
        self.assertEqual(len(report["rows"]), 6)
        self.assertEqual({row["id"] for row in report["rows"]},
                         {f"{case}_{arm}" for case in ("au", "su", "wk")
                          for arm in ("candidate", "original")})
        for row in report["rows"]:
            self.assertTrue(row["version_1_every_result_field_equal"])
            self.assertEqual(row["ignored_result_fields"], [])
            self.assertFalse(row["timing"]["hardware_timing_admitted"])
        self.assertEqual(report["legacy"]["status"], "PASS")
        self.assertEqual(report["legacy"]["correctness_admitted_cases"], 5)
        self.assertFalse(report["legacy"]["ignored_result_fields"])
        for record in report["verification"].values():
            self.assertEqual(record["exit_code"], 0)
            self.assertFalse(record.get("timed_out", False))

    def test_every_archive_member_and_parent_identity(self):
        self.assertEqual(len(self.pins), len(self.index["files"]))
        with (PARENT / "sst_raw_index.json").open("rb") as stream:
            self.assertEqual(digest(stream), self.index["parent_raw_dependency"]["sha256"])
        found = set()
        with self.open_archive() as archive:
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

    def test_complete_output_bytes_equal_parent_and_board(self):
        for row in self.report["rows"]:
            name = row["id"]
            expected = self.parent_pins[f"board/{name}/result.txt"]
            self.assertEqual(self.pins[f"parent_results/{name}/result.json.values.txt"], expected)
            for run in ("matrix_final", "legacy_v1_replay"):
                self.assertEqual(self.pins[f"campaign/{run}/{name}/result.json.values.txt"], expected)
        self.assertEqual(len([path for path in self.pins if path.startswith("fixtures/")]), 3)
        for case in ("au", "su", "wk"):
            self.assertEqual(self.pins[f"fixtures/{case}.bin"], self.parent_pins[f"fixtures/{case}.bin"])

    def test_one_source_and_plugin_for_all_final_runs(self):
        expected = self.report["legacy"]["candidate_identity"]
        paths = {f"campaign/{run}/{row['id']}/manifest.json"
                 for run in ("matrix_final", "legacy_v1_replay") for row in self.report["rows"]}
        found = set()
        with self.open_archive() as archive:
            for member in archive:
                if member.name in paths:
                    manifest = json.load(archive.extractfile(member))
                    self.assertEqual(manifest["source"], expected["source"])
                    self.assertEqual(manifest["plugin"]["plugin_sha256"], expected["plugin_sha256"])
                    found.add(member.name)
        self.assertEqual(found, paths)
        self.assertEqual(self.pins["binaries/libspine_cycle.so"], expected["plugin_sha256"])

    def test_runtime_optimization_keeps_complete_and_partial_evidence_separate(self):
        complete = self.report["runtime_only_optimization_equivalence"]
        self.assertEqual({row["id"] for row in complete},
                         {f"{case}_candidate" for case in ("au", "su", "wk")})
        for row in complete:
            self.assertTrue(row["every_result_field_equal"])
            self.assertTrue(row["complete_result_bytes_equal"])
            self.assertEqual(row["ignored_fields"], [])
        partial = self.report["partial_observation_equivalence"]
        self.assertEqual(partial["status"], "PASS")
        self.assertEqual(partial["claim"], "partial_observation_equivalence_not_workload_correctness")
        self.assertEqual({row["id"] for row in partial["rows"]}, {"au_original", "su_original"})
        for row in partial["rows"]:
            self.assertTrue(row["every_result_field_equal"])
            self.assertEqual(row["ignored_fields"], [])
            self.assertTrue(row["complete_state_bytes_equal"])
            self.assertGreater(row["observed_cycles"], 0)


if __name__ == "__main__":
    unittest.main()
