from array import array
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact, oracle
from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import active_min_inputs as fixtures


class ActiveMinFixtureTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.root / "source"
        self.source.mkdir()
        self.host = self.root / "host"
        self.host.touch()
        self.write("execution", [0x3447524F, 1, 4, 3, 65536, 65536, 1, 1,
                                 0, 0, 0, 0, 65536, 0, 16, 0])
        self.write("csr_offsets", [0, 0, 3, 3, 3])
        self.write("csr_destinations", [0, 2, 3])
        self.write("tasks", [1, 0, 1, 2, 1, 3, *([1, fixtures.PADDING] * 5)])
        self.write("initial", [0])
        self.write("degrees", [0])

    def write(self, name, words):
        path = self.source / f"{name}.u32le"
        path.unlink(missing_ok=True)
        fixtures.write_words(path, array("I", words))

    def offline(self, host, algorithm, inputs, output):
        self.assertEqual(host, self.host)
        self.assertEqual((inputs / "tasks.u32le").read_bytes(), (self.source / "tasks.u32le").read_bytes())
        task = oracle.read_words(inputs / "sssp_tasks.u32le", 16)
        self.assertEqual(list(task), [1, 16 << 19, 1, (2 << 19) | 2, 1, (3 << 19) | 3,
                                      *([1, fixtures.PADDING] * 5)])
        expected, initial = output / "expected", output / "result"
        active = fixtures.ACTIVE
        if algorithm == "cc":
            self.assertEqual(list(oracle.read_words(inputs / "cc_initial.u32le", 65536)[:4]), [0, active, 2, 3])
            words = [0, 0, active, active]
        else:
            self.assertEqual(list(oracle.read_words(inputs / "sssp_weights.u32le", 3)), [16, 2, 3])
            self.assertEqual(list(oracle.read_words(inputs / "sssp_initial.u32le", 65536)[:4]),
                             [fixtures.INFINITY, active, fixtures.INFINITY, fixtures.INFINITY])
            words = [active | 16, 0, active | 2, active | 3]
        fixtures.write_words(expected, array("I", words + [0] * (65536 - 4) + list(fixtures.GUARD)))
        initial.touch()
        return {"vertices": 4, "logical_edges": 3, "tasks": 1}, artifact.identity(expected), artifact.identity(initial)

    def test_shared_graph_and_policy_specific_initial_state(self):
        with patch.object(fixtures.active_min, "read_offline", side_effect=self.offline) as offline:
            report = fixtures.prepare(self.source, self.host, self.root / "output")
        self.assertEqual(offline.call_count, 2)
        self.assertEqual(report["seed"], 1)
        self.assertEqual(report["audits"]["cc"]["improved_vertices"], 2)
        self.assertEqual(report["audits"]["weighted_sssp"]["improved_vertices"], 3)
        self.assertFalse(report["hardware_timing_measured"])

    def test_rejects_duplicate_edges_and_incomplete_publication(self):
        self.write("csr_destinations", [0, 2, 2])
        with patch.object(fixtures.active_min, "read_offline") as offline:
            first = self.root / "duplicate"
            with self.assertRaisesRegex(ValueError, "duplicate edge"):
                fixtures.prepare(self.source, self.host, first)
            self.assertEqual(json.loads((first / "manifest.json").read_text())["status"], "FAILED_RETAINED")
            self.write("execution", [0x3447524F, 1, 4, 3, 65536, 0, 1, 1, *([0] * 8)])
            with self.assertRaisesRegex(ValueError, "published"):
                fixtures.prepare(self.source, self.host, self.root / "incomplete")
            offline.assert_not_called()
