"""Reject changed work, declarations, partial state and missing worker evidence."""

import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.a4_control.analysis import candidate, matrix
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.a4_control.contract import run_specs
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.a4_control.execution import case_command


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name)
        self.geometry = {"padded_vertices": 16}
        self.layout = {"partitions": [{"rows_visited": n} for n in (16, 15, 9, 8)]}
        self.outputs = []
        for name in ("k4_primary", "k4_source0", "k4_source1"):
            path = self.state / (name + ".u32le")
            path.write_bytes(struct.pack("<16I", *range(16)))
            self.outputs.append({"path": str(path), "sha256": sha256_file(path), "bytes": 64})
        self.skip = {"counters": {"path": "actual_k4", "passed": True,
            "full_state_and_traffic_pass": True, "replicas": 3, "checked_words_per_replica": 16,
            "cycles": 1000, "read_bytes": 4096, "row_reads": 48, "extent_reads": 4,
            "segment_reads": 4, "source_lines": 4, "physical_packets": 8, "live_edges": 8,
            "dummy_edges": 56, "active_vertices": 1, "write_bytes": 196}}
        self.frozen = {"paths": [{"cycles": 100}, dict(self.skip["counters"], cycles=1200)],
                       "outputs": self.outputs}
        self.metadata = {"row_line_reads": 1, "empty_segment_exit_cycles": 0, "fixed_rounds": 1,
                         "hardware_timing_admitted": False, "strict_resource_match_admitted": False}
        self.counters = dict(self.skip["counters"], cycles=900, row_reads=7, read_bytes=1472)
        self.invocations = [{"round": 1, "partition": p, "worker": p, "adapter": adapter,
                             "start": 0, "end": 800 + p} for p in range(4) for adapter in (True, False)]

    def stdout(self):
        return "\n".join(["MODEL_CONTROL " + json.dumps(self.metadata),
                          "REAL_ROUND " + json.dumps(self.counters),
                          *("INVOCATION " + json.dumps(row) for row in self.invocations)])

    def admit(self):
        return candidate(self.stdout(), self.state, self.geometry, self.frozen,
                         self.skip, "whole_line", self.layout)

    def test_expected_traffic_and_all_workers(self):
        row = self.admit()
        self.assertEqual(row["k4_over_A4_cycles_diagnostic_only"], 9)
        self.assertEqual(len(row["invocations"]), 8)

    def test_incorrect_whole_line_request_count(self):
        self.counters["row_reads"] += 1
        with self.assertRaisesRegex(ValueError, "traffic"):
            self.admit()

    def test_unaccounted_bytes(self):
        self.counters["read_bytes"] += 64
        with self.assertRaisesRegex(ValueError, "traffic"):
            self.admit()

    def test_other_work_cannot_disappear(self):
        self.counters["dummy_edges"] -= 8
        with self.assertRaisesRegex(ValueError, "traffic"):
            self.admit()

    def test_skip_empty_must_preserve_exact_cycles(self):
        self.metadata["row_line_reads"] = 0
        self.counters = dict(self.skip["counters"], cycles=999)
        with self.assertRaisesRegex(ValueError, "cycles"):
            candidate(self.stdout(), self.state, self.geometry, self.frozen, self.skip, "skip_empty", self.layout)

    def test_hardware_claim_rejected(self):
        self.metadata["hardware_timing_admitted"] = True
        with self.assertRaisesRegex(ValueError, "declaration"):
            self.admit()

    def test_bool_cannot_be_counter(self):
        self.counters["row_reads"] = True
        with self.assertRaisesRegex(ValueError, "counter"):
            self.admit()

    def test_partial_or_corrupt_state_rejected(self):
        (self.state / "k4_source0.u32le").write_bytes(b"\0" * 64)
        with self.assertRaisesRegex(ValueError, "state"):
            self.admit()

    def test_missing_worker_and_duplicate_rejected(self):
        self.invocations[-1] = copy.deepcopy(self.invocations[0])
        with self.assertRaisesRegex(ValueError, "partition execution"):
            self.admit()

    def test_completion_after_total_rejected(self):
        self.invocations[0]["end"] = 901
        with self.assertRaisesRegex(ValueError, "bounds"):
            self.admit()

    def test_fixed_bounded_commands(self):
        self.assertEqual(len(run_specs()), 24)
        command = case_command(Path("/fresh"), "cold", 64, 0, "whole_line")
        self.assertEqual(command[:3], ["taskset", "-c", "112-113"])
        self.assertEqual(command[-3:], ["100000000", "0", "1"])
        with self.assertRaisesRegex(ValueError, "matrix"):
            matrix([])


if __name__ == "__main__":
    unittest.main()
