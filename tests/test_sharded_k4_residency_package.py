"""Recheck every archived resident run and the before/after DMA trace offline."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.analysis import analyze_log
from spine_cycle_sim.experiments.sharded_k4_stages.input_residency import residency_record, summarize
from spine_cycle_sim.experiments.sharded_k4_stages.residency_matrix import summarize_matrix
from spine_cycle_sim.experiments.sharded_k4_stages.runtime_trace import parse_vtf, trace_transfers


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst"
PACKAGE = PARENT / "input_residency"


class ResidencyPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads((PACKAGE / "residency_raw_index.json").read_text())
        cls.report = json.loads((PACKAGE / "residency.json").read_text())
        with tarfile.open(PACKAGE / "raw_residency.tar.gz") as stream:
            cls.members = stream.getmembers()
            cls.files = {m.name: stream.extractfile(m).read() for m in cls.members}

    def load(self, name):
        return json.loads(self.files[name])

    def test_safe_archive_and_all_hashes(self):
        pins = {p["archive_path"]: p["sha256"] for p in self.index["files"]}
        self.assertEqual(len(pins), len(self.members))
        self.assertEqual(set(pins), set(self.files))
        for m in self.members:
            self.assertTrue(m.isfile())
            self.assertFalse(PurePosixPath(m.name).is_absolute())
            self.assertNotIn("..", PurePosixPath(m.name).parts)
            self.assertEqual(hashlib.sha256(self.files[m.name]).hexdigest(), pins[m.name])
        self.assertEqual(hashlib.sha256((PACKAGE / "raw_residency.tar.gz").read_bytes()).hexdigest(),
                         self.index["archive"]["sha256"])
        for pin in self.index["dependencies"]:
            local = PARENT / Path(pin["path"]).parent.name / Path(pin["path"]).name
            self.assertEqual(hashlib.sha256(local.read_bytes()).hexdigest(), pin["sha256"])

    def test_all_thirty_complete_results_and_raw_logs(self):
        count = 0
        for group in ("control", "matrix", "trace"):
            attempts = self.load(group + "/attempts.json")
            saved = self.load(group + "/summary.json")
            manifest = self.load(group + "/manifest.json")
            self.assertEqual(attempts, saved["attempts"])
            if group == "control":
                self.assertEqual(summarize(attempts), saved)
            if group == "matrix":
                self.assertEqual(summarize_matrix(attempts, manifest["predictions_ms"]), saved)
                self.assertEqual(saved["rows"], self.report["resident_matrix"])
            for a in attempts:
                count += 1
                if group == "matrix":
                    name, enabled = f"r{a['repeat']}_{a['graph']}_{a['arm']}", True
                elif group == "control":
                    name = "profiled_on" if a["profiled"] else f"r{a['repeat']}_{a['arm']}"
                    enabled = a["arm"] == "on"
                else:
                    name, enabled = a["arm"], False
                prefix = f"{group}/{name}/"
                log = self.files[prefix + "board/run.log"].decode()
                board = analyze_log(log, require_trace=True)
                self.assertEqual(board, a["analysis"])
                self.assertEqual(board["result"]["mismatches"], "0")
                initial = residency_record(log, enabled=enabled,
                                           partitions=int(board["result"]["destination_partitions"]))
                if "residency" in a:
                    self.assertEqual(initial, a["residency"])
                resources = self.load(prefix + "process.resources.json")
                self.assertEqual(resources, a["resources"])
                self.assertEqual(resources["exit_code"], 0)
                self.assertFalse(resources["timed_out"])
                self.assertEqual(resources["memory_limit_gib"], 8)
                self.assertEqual(resources["reserve_gib"], 16)
                digest = a["result"]["sha256"]
                self.assertEqual(hashlib.sha256(self.files[f"complete_results/{digest}.txt"]).hexdigest(), digest)
        self.assertEqual(count, 30)
        self.assertEqual(count, self.report["attempt_count"])

    def test_transfer_intervention_and_claim_boundaries(self):
        for label, group, directory, position in (("before", "trace", "profiled", 1),
                                                  ("after", "control", "profiled_on", -1)):
            trace = parse_vtf(self.files[f"{group}/{directory}/opencl_trace.csv"].decode())
            board = self.load(group + "/attempts.json")[position]["analysis"]
            result = trace_transfers(trace, board)
            self.assertEqual(result, self.report["runtime_" + label])
            self.assertEqual(result["aligned_kernels"], 56)
            self.assertEqual(result["compute_write_count"], 16 if label == "before" else 0)
            self.assertEqual(result["compute_write_bytes"], 145939200 if label == "before" else 0)
        for key in ("timing_fit_performed", "hardware_timing_admitted", "original_A4_match_admitted",
                    "exclusive_stage_calibration_admitted"):
            self.assertFalse(self.report[key])


if __name__ == "__main__":
    unittest.main()
