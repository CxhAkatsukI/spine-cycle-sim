"""Recheck the empty-exit checkpoint using portable archives, not local runs."""

import hashlib
import json
from pathlib import Path, PurePosixPath
from statistics import median
import tarfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_exit_delivery import compare_payloads
from spine_cycle_sim.experiments.sharded_k4_stages.row_sweep_analysis import incremental_slopes


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst"
PACKAGE = PARENT / "empty_exit_model"


def digest(stream):
    checksum = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        checksum.update(chunk)
    return checksum.hexdigest()


class EmptyExitPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((PACKAGE / "model.json").read_text())
        cls.index = json.loads((PACKAGE / "model_raw_index.json").read_text())
        cls.pins = {r["archive_path"]: r["sha256"] for r in cls.index["files"]}
        old = json.loads((PARENT / "empty_rows/empty_rows_raw_index.json").read_text())
        cls.old_pins = {r["archive_path"]: r["sha256"] for r in old["files"]}

    def test_complete_control_without_full_timing_admission(self):
        self.assertEqual(self.report["status"], "EMPTY_EXIT_CONTROL_PASS_FULL_MATRIX_PENDING")
        for field in ("hardware_timing_admitted", "original_A4_match_admitted", "timing_fit_performed"):
            self.assertFalse(self.report[field])
        legacy = self.report["legacy"]
        self.assertEqual(legacy["status"], "PASS")
        self.assertEqual(legacy["correctness_admitted_cases"], 5)
        self.assertEqual(legacy["ignored_result_fields"], [])
        self.assertEqual([r["vertices"] for r in self.report["sweep"]["rows"]], [4096, 8192, 16384, 32768])
        self.assertEqual(len(self.report["sweep"]["replays"]), 8)
        for name, gate in self.report["verification"].items():
            self.assertEqual(gate["exit_code"], 0)
            if name == "python_gates":
                self.assertEqual(gate["stop_reason"], "process_exit")
            else:
                self.assertFalse(gate["timed_out"])

    def test_all_archive_hashes_and_dependencies(self):
        archive_path = PACKAGE / "raw_model.tar.gz"
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
        paths = ("empty_row_rtl/rtl_raw_index.json", "empty_rows/empty_rows_raw_index.json",
                 "routed_streams/streams_raw_index.json")
        self.assertEqual(len(self.index["dependencies"]), len(paths))
        for path, pin in zip(paths, self.index["dependencies"]):
            with (PARENT / path).open("rb") as stream:
                self.assertEqual(digest(stream), pin["sha256"])

    def test_rederive_outputs_sources_traffic_and_timing(self):
        expected = self.report["legacy"]["candidate_identity"]
        self.assertEqual(self.pins["binaries/libspine_cycle.so"], expected["plugin_sha256"])
        objects = {}
        with tarfile.open(PACKAGE / "raw_model.tar.gz", "r|gz") as archive:
            for member in archive:
                if member.name.startswith("campaign/sweep/") and member.name.endswith(("/manifest.json", "/result.json")):
                    objects[member.name] = json.load(archive.extractfile(member))
        self.assertEqual(len(objects), 32)
        for row in self.report["sweep"]["rows"]:
            vertices = row["vertices"]
            self.assertEqual(self.pins[f"inputs/{vertices}/prepared.bin"],
                             self.old_pins[f"campaign/{vertices}/prepared.bin"])
            for arm in ("original", "candidate"):
                old = f"campaign/{vertices}/{arm}"
                replay = f"campaign/sweep/replay_v2/{vertices}/{arm}"
                corrected = f"campaign/sweep/corrected_v4/{vertices}/{arm}"
                self.assertEqual(self.pins[f"{replay}/result.json"], self.old_pins[f"{old}/result.json"])
                for prefix in (replay, corrected):
                    self.assertEqual(self.pins[f"{prefix}/result.json.values.txt"],
                                     self.old_pins[f"{old}/result.json.values.txt"])
                    manifest = objects[f"{prefix}/manifest.json"]
                    self.assertEqual(manifest["source"], expected["source"])
                    self.assertEqual(manifest["plugin"]["plugin_sha256"], expected["plugin_sha256"])
                before, after = objects[f"{replay}/result.json"], objects[f"{corrected}/result.json"]
                self.assertEqual(before["profile_id"], "grasu_regraph_routed_sssp_compute_v2")
                self.assertEqual(after["profile_id"], "grasu_regraph_routed_sssp_compute_v4")
                compare_payloads(before, after)
                events = {(e["stage"], e["round"]): e for e in after["invocations"]}
                durations, tails = [], []
                for index in (1, 2):
                    adapter, gather = events["adapter", index], events["gather", index]
                    durations.append((adapter["end"] - adapter["start"]) * 1000 / 150)
                    tails.append(max(0, adapter["end"] - gather["end"]) * 1000 / 150)
                self.assertEqual(durations, row["arms"][arm]["model_round_duration_ns"])
                self.assertEqual(tails, row["arms"][arm]["model_round_tail_ns"])
                self.assertEqual(median(durations), row["arms"][arm]["model_median_duration_ns"])
        self.assertEqual(incremental_slopes(self.report["sweep"]["rows"]), self.report["sweep"]["slopes"])


if __name__ == "__main__":
    unittest.main()
