"""Strict model declarations, reference replay, conserved work and finite matrix."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.a4_control.analysis import admit, matrix
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.a4_control.contract import metadata, run_specs
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.a4_control.execution import case_command


class CrossRowA4AdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name)
        self.geometry = {"padded_vertices": 16}
        outputs = []
        for name in ("k4_primary", "k4_source0", "k4_source1"):
            path = self.state / (name + ".u32le")
            path.write_bytes(bytes(range(64)))
            outputs.append({"path": str(path), "bytes": 64, "sha256": sha256_file(path)})
        self.counters = {"path": "actual_k4", "passed": True, "full_state_and_traffic_pass": True,
                         "cycles": 900, "live_edges": 8, "dummy_edges": 56, "read_bytes": 4096,
                         "write_bytes": 196, "extent_reads": 4, "row_reads": 8, "segment_reads": 4,
                         "source_lines": 4, "physical_packets": 8, "active_vertices": 1,
                         "checked_words_per_replica": 16, "replicas": 3}
        self.invocations = [{"round": 1, "partition": p, "worker": p, "adapter": a,
                             "start": 0, "end": 800 + p} for p in range(4) for a in (True, False)]
        self.basis = {"cases": [{"mode": "cold", "latency": 64, "reverse": 0, "arm": "original",
                                 "paths": [{"cycles": 100}]},
                                {"mode": "cold", "latency": 64, "reverse": 0, "arm": "whole_line",
                                 "counters": dict(self.counters, cycles=1000), "outputs": outputs,
                                 "invocations": copy.deepcopy(self.invocations)}]}
        self.declaration = metadata("cross_row")

    def stdout(self):
        return "\n".join(["MODEL_CONTROL " + json.dumps(self.declaration),
                          "REAL_ROUND " + json.dumps(self.counters),
                          *("INVOCATION " + json.dumps(row) for row in self.invocations)])

    def check(self, arm="cross_row"):
        return admit(self.stdout(), self.state, self.geometry, self.basis, ("cold", 64, 0, arm))

    def test_complete_conservation(self):
        row = self.check()
        self.assertEqual(row["k4_over_A4_cycles_diagnostic_only"], 9)
        self.assertEqual(len(row["outputs"]), 3)
        self.assertEqual(len(row["invocations"]), 8)

    def test_reference_cycles_are_not_relaxed(self):
        self.declaration = metadata("whole_line")
        with self.assertRaisesRegex(ValueError, "reference replay"):
            self.check("whole_line")
        self.counters["cycles"] = 1000
        self.check("whole_line")
        self.invocations[0]["end"] += 1
        with self.assertRaisesRegex(ValueError, "invocation replay"):
            self.check("whole_line")

    def test_every_work_field_preserved(self):
        before = dict(self.counters)
        for key in before.keys() - {"cycles", "path"}:
            self.counters = dict(before)
            self.counters[key] = not before[key] if type(before[key]) is bool else before[key] + 1
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "traffic"):
                self.check()

    def test_bool_is_not_cycle_count(self):
        self.counters["cycles"] = True
        with self.assertRaises(ValueError):
            self.check()

    def test_missing_duplicate_and_wrong_worker(self):
        before = copy.deepcopy(self.invocations)
        for changed in (before[:-1], before + before[:1], [dict(before[0], worker=3), *before[1:]]):
            self.invocations = changed
            with self.assertRaisesRegex(ValueError, "invocation"):
                self.check()

    def test_hardware_claim_old_version_and_unknown_lines_rejected(self):
        for key, value in (("version", "old_version"), ("hardware_timing_admitted", True),
                           ("cross_row_pipeline", 0), ("cross_row_pipeline", True)):
            self.declaration = dict(metadata("cross_row"), **{key: value})
            with self.assertRaisesRegex(ValueError, "declaration"):
                self.check()
        self.declaration = metadata("cross_row")
        with self.assertRaisesRegex(ValueError, "unknown output"):
            admit(self.stdout() + "\nEXTRA {}", self.state, self.geometry, self.basis, ("cold", 64, 0, "cross_row"))

    def test_corrupted_or_extra_state_rejected(self):
        path = self.state / "extra.u32le"
        path.write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "state replica"):
            self.check()
        path.unlink()
        (self.state / "k4_source0.u32le").write_bytes(b"x" * 64)
        with self.assertRaisesRegex(ValueError, "oracle"):
            self.check()

    def test_matrix_requires_every_predeclared_case(self):
        self.assertEqual(len(run_specs()), 18)
        with self.assertRaisesRegex(ValueError, "matrix"):
            matrix([])
        cases = []
        for mode, latency, reverse, arm in run_specs():
            cases.append({"mode": mode, "latency": latency, "reverse": reverse, "arm": arm,
                          "outputs": self.basis["cases"][1]["outputs"],
                          "counters": {"cycles": latency * 100, "live_edges": 8}})
        self.assertFalse(matrix(cases)["hardware_timing_admitted"])
        cases[-1]["counters"]["cycles"] += 1
        with self.assertRaisesRegex(ValueError, "registration order"):
            matrix(cases)

    def test_fixed_bounded_command_and_distinct_arm(self):
        command = case_command(Path("/fresh"), "warm_update", 128, 1, "cross_row")
        self.assertEqual(command[:3], ["taskset", "-c", "112-113"])
        self.assertEqual(command[-4:], ["128", "1", "100000000", "1"])
        self.assertEqual(case_command(Path("/fresh"), "cold", 64, 0, "whole_line")[-1], "0")


if __name__ == "__main__":
    unittest.main()
