"""Portable raw evidence and unchanged-window gates for routed FIFO depths."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.stream_contract import validate_design
from spine_cycle_sim.experiments.sharded_k4_stages.stream_delivery import compare_stream_results


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst"
PACKAGE = PARENT / "routed_streams"


def digest(stream):
    checksum = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        checksum.update(chunk)
    return checksum.hexdigest()


class StreamPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((PACKAGE / "streams.json").read_text())
        cls.index = json.loads((PACKAGE / "streams_raw_index.json").read_text())
        cls.pins = {row["archive_path"]: row["sha256"] for row in cls.index["files"]}
        cls.parent = json.loads((PARENT / "sst_raw_index.json").read_text())
        cls.parent_pins = {row["archive_path"]: row["sha256"] for row in cls.parent["files"]}

    def test_no_calibration_claim_and_complete_matrix(self):
        self.assertEqual(self.report["status"], "ROUTED_STREAM_DEPTHS_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC")
        for flag in ("hardware_timing_admitted", "original_A4_match_admitted", "timing_fit_performed"):
            self.assertFalse(self.report[flag])
        self.assertEqual(len(self.report["rows"]), 6)
        self.assertEqual({r["id"] for r in self.report["rows"]},
                         {f"{case}_{arm}" for case in ("au", "su", "wk") for arm in ("original", "candidate")})
        self.assertEqual(self.report["legacy"]["status"], "PASS")
        self.assertEqual(self.report["legacy"]["correctness_admitted_cases"], 5)
        self.assertFalse(self.report["legacy"]["ignored_result_fields"])
        for record in self.report["verification"].values():
            self.assertEqual(record["exit_code"], 0)
            self.assertFalse(record["timed_out"])

    def test_entire_archive_and_dependencies(self):
        archive_path = PACKAGE / "raw_streams.tar.gz"
        with archive_path.open("rb") as stream:
            self.assertEqual(digest(stream), self.index["archive"]["sha256"])
        self.assertEqual(len(self.pins), len(self.index["files"]))
        found = set()
        with tarfile.open(archive_path, "r|gz") as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                self.assertFalse(path.is_absolute())
                self.assertNotIn("..", path.parts)
                self.assertTrue(member.isfile())
                self.assertNotIn(member.name, found)
                found.add(member.name)
                self.assertEqual(digest(archive.extractfile(member)), self.pins[member.name])
        self.assertEqual(found, set(self.pins))
        self.assertEqual(len(self.index["dependencies"]), 2)
        for path, pin in zip((PARENT / "independent_channels/channels_raw_index.json",
                              PARENT / "sst_raw_index.json"), self.index["dependencies"]):
            with path.open("rb") as stream:
                self.assertEqual(digest(stream), pin["sha256"])

    def test_full_outputs_inputs_and_source_identity(self):
        expected = self.report["legacy"]["candidate_identity"]
        self.assertEqual(self.pins["binaries/libspine_cycle.so"], expected["plugin_sha256"])
        for row in self.report["rows"]:
            name = row["id"]
            for version in ("replay_v2", "matrix_v3"):
                self.assertEqual(self.pins[f"campaign/{version}/{name}/result.json.values.txt"],
                                 self.parent_pins[f"board/{name}/result.txt"])
        self.assertEqual(len([p for p in self.pins if p.startswith("fixtures/")]), 3)
        for case in ("au", "su", "wk"):
            self.assertEqual(self.pins[f"fixtures/{case}.bin"], self.parent_pins[f"fixtures/{case}.bin"])
        manifests = {f"campaign/{version}/{row['id']}/manifest.json"
                     for version in ("replay_v2", "matrix_v3") for row in self.report["rows"]}
        found = set()
        with tarfile.open(PACKAGE / "raw_streams.tar.gz", "r|gz") as archive:
            for member in archive:
                if member.name in manifests:
                    manifest = json.load(archive.extractfile(member))
                    self.assertEqual(manifest["source"], expected["source"])
                    self.assertEqual(manifest["plugin"]["plugin_sha256"], expected["plugin_sha256"])
                    found.add(member.name)
        self.assertEqual(found, manifests)

    def test_rederive_result_gates_and_both_routed_designs(self):
        paths = {f"{prefix}/{row['id']}/result.json"
                 for prefix in ("parent", "campaign/replay_v2", "campaign/matrix_v3")
                 for row in self.report["rows"]}
        paths.update(f"campaign/route/{arm}.bd" for arm in ("original", "candidate"))
        objects = {}
        with tarfile.open(PACKAGE / "raw_streams.tar.gz", "r|gz") as archive:
            for member in archive:
                if member.name in paths:
                    objects[member.name] = json.load(archive.extractfile(member))
        self.assertEqual(set(objects), paths)
        for row in self.report["rows"]:
            comparison = compare_stream_results(*(objects[f"{prefix}/{row['id']}/result.json"]
                                                 for prefix in ("parent", "campaign/replay_v2", "campaign/matrix_v3")))
            for key, value in comparison.items():
                self.assertEqual(row[key], value)
            self.assertFalse(row["timing"]["hardware_timing_admitted"])
        for row in self.report["routed_designs"]:
            self.assertEqual(validate_design(objects[f"campaign/route/{row['arm']}.bd"]), row["streams"])
            self.assertEqual(self.pins[f"campaign/route/{row['arm']}.bd"], row["sha256"])


if __name__ == "__main__":
    unittest.main()
