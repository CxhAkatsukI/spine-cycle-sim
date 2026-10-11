"""Verify real-graph v4 evidence from portable packages, without local runs."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.analysis import analyze_log
from spine_cycle_sim.experiments.sharded_k4_stages.row_exit_matrix import compare_real_results
from spine_cycle_sim.experiments.sharded_k4_stages.sst_timing import timing_diagnostic


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst"
PACKAGE = PARENT / "empty_exit_matrix"


def digest(stream):
    checksum = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        checksum.update(chunk)
    return checksum.hexdigest()


class EmptyExitMatrixPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((PACKAGE / "matrix.json").read_text())
        cls.index = json.loads((PACKAGE / "matrix_raw_index.json").read_text())
        cls.pins = {r["archive_path"]: r["sha256"] for r in cls.index["files"]}
        cls.objects = {}
        cls.logs = {}
        with tarfile.open(PACKAGE / "raw_matrix.tar.gz", "r|gz") as archive:
            for member in archive:
                if member.name.endswith(".json"):
                    cls.objects[member.name] = json.load(archive.extractfile(member))
                elif member.name.startswith("board/") and member.name.endswith("run.log"):
                    cls.logs[member.name] = archive.extractfile(member).read().decode()

    def test_complete_predeclared_matrix_without_timing_admission(self):
        self.assertEqual(self.report["status"], "EMPTY_EXIT_REAL_MATRIX_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC")
        for field in ("hardware_timing_admitted", "original_A4_match_admitted", "timing_fit_performed"):
            self.assertFalse(self.report[field])
        expected = {f"{case}_{arm}" for case in ("au", "su", "wk") for arm in ("original", "candidate")}
        self.assertEqual({r["id"] for r in self.report["rows"]}, expected)
        self.assertEqual(len(self.report["rows"]), 6)
        for name in ("replay_v3", "matrix_v4"):
            matrix = self.objects[f"campaign/{name}/summary.json"]
            self.assertEqual(matrix["status"], "FUNCTIONAL_MATRIX_PASS_TIMING_UNADMITTED")
            self.assertEqual({r["id"] for r in matrix["rows"]}, expected)
            self.assertEqual(len(matrix["rows"]), 6)
            self.assertTrue(matrix["contract_unchanged"])
            self.assertFalse(matrix["hardware_timing_admitted"])
            resources = self.objects[f"campaign/{name}.resources.json"]
            self.assertEqual(resources["exit_code"], 0)
            self.assertFalse(resources["timed_out"])
            contract = self.objects[f"campaign/{name}/matrix.json"]
            self.assertEqual(contract["jobs"], 2)
            self.assertEqual(contract["matrix"]["memory_limit_gib"], 8)
            self.assertEqual(contract["matrix"]["reserve_gib"], 16)

    def test_archive_and_dependency_hashes(self):
        with (PACKAGE / "raw_matrix.tar.gz").open("rb") as stream:
            self.assertEqual(digest(stream), self.index["archive"]["sha256"])
        self.assertEqual(len(self.pins), len(self.index["files"]))
        found = set()
        with tarfile.open(PACKAGE / "raw_matrix.tar.gz", "r|gz") as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                self.assertFalse(path.is_absolute())
                self.assertNotIn("..", path.parts)
                self.assertTrue(member.isfile())
                self.assertNotIn(member.name, found)
                found.add(member.name)
                self.assertEqual(digest(archive.extractfile(member)), self.pins[member.name])
        self.assertEqual(found, set(self.pins))
        paths = ("empty_exit_model/model_raw_index.json", "routed_streams/streams_raw_index.json", "sst_raw_index.json")
        self.assertEqual(len(self.index["dependencies"]), len(paths))
        for path, pin in zip(paths, self.index["dependencies"]):
            with (PARENT / path).open("rb") as stream:
                self.assertEqual(digest(stream), pin["sha256"])

    def test_source_and_plugin_equal_the_tested_control(self):
        control = json.loads((PARENT / "empty_exit_model/model.json").read_text())["legacy"]["candidate_identity"]
        binding = self.objects["campaign/binding.json"]
        self.assertEqual(self.report["plugin_reused"], binding["plugin"])
        self.assertEqual(binding["plugin"]["sha256"], control["plugin_sha256"])
        self.assertTrue(self.report["numerical_sources_unchanged_from_control"])
        old = {r["path"]: r["sha256"] for r in control["source"]["files"]}
        new = {r["path"]: r["sha256"] for r in binding["source"]["files"]}
        extra = "spine_cycle_sim/experiments/sharded_k4_stages/row_exit_matrix.py"
        self.assertEqual(new, {**old, extra: self.pins["source/row_exit_matrix.py"]})
        for row in self.report["rows"]:
            for name in ("replay_v3", "matrix_v4"):
                manifest = self.objects[f"campaign/{name}/{row['id']}/manifest.json"]
                self.assertEqual(manifest["source"], binding["source"])
                self.assertEqual(manifest["plugin"]["plugin_sha256"], binding["plugin"]["sha256"])

    def test_rederive_results_outputs_and_nominal_timing(self):
        prior = json.loads((PARENT / "routed_streams/streams_raw_index.json").read_text())
        old_pins = {r["archive_path"]: r["sha256"] for r in prior["files"]}
        board = json.loads((PARENT / "sst_raw_index.json").read_text())
        board_pins = {r["archive_path"]: r["sha256"] for r in board["files"]}
        for row in self.report["rows"]:
            name = row["id"]
            before = f"parent/{name}/result.json"
            replay = f"campaign/replay_v3/{name}"
            corrected = f"campaign/matrix_v4/{name}"
            old = f"campaign/matrix_v3/{name}"
            self.assertEqual(self.pins[before], old_pins[f"{old}/result.json"])
            self.assertEqual(self.pins[f"{replay}/result.json"], self.pins[before])
            for prefix in (replay, corrected):
                result_hash = self.pins[f"{prefix}/result.json.values.txt"]
                self.assertEqual(result_hash, old_pins[f"{old}/result.json.values.txt"])
                self.assertEqual(result_hash, board_pins[f"board/{name}/result.txt"])
                fixture = self.objects[f"{prefix}/summary.json"]["fixture"]
                old_fixture = self.objects[f"campaign/replay_v3/{name}/summary.json"]["fixture"]
                self.assertEqual(fixture["sha256"], old_fixture["sha256"])
            results = [self.objects[path] for path in (before, f"{replay}/result.json", f"{corrected}/result.json")]
            derived = compare_real_results(*results)
            for key, value in derived.items():
                self.assertEqual(row[key], value)
            log = f"board/{name}/run.log"
            self.assertEqual(self.pins[log], board_pins[log])
            measured = analyze_log(self.logs[log], require_trace=True)
            timing = timing_diagnostic(results[-1], measured)
            self.assertEqual(row["timing"], timing)
            self.assertEqual(timing, self.objects[f"{corrected}/summary.json"]["timing"])


if __name__ == "__main__":
    unittest.main()
