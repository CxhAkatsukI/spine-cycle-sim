import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    respr_matrix as matrix, resident_matrix,
)


class ResprMatrixTest(unittest.TestCase):
    def run_queue(self, *, reject=False):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            group = root / "group"
            group.mkdir()
            (group / "memory.peak").write_text("100")
            (group / "memory.events").write_text("oom_kill 0")
            args = SimpleNamespace(unit="parent.service", invocation="a" * 32, wait_seconds=1,
                                   child_prefix="test-respr", board_wait_seconds=1,
                                   output=root / "matrix", previous=root / "previous",
                                   parent=root / "parent.json")
            pins, image, gate = {"parent": {"sha256": "b" * 64}}, {"path": "image"}, {"r": True, "g": True}
            calls = []

            def declare(_, name):
                return dict(case={"dataset": name}, inputs=[], memory_gib=32, status="PREDECLARED")

            def one(command, log, output, dataset, actual_gate, boundary):
                self.assertEqual(actual_gate, gate)
                self.assertEqual(boundary, matrix.BOUNDARY)
                self.assertIn("--property=MemoryMax=32G", command)
                self.assertIn("--property=MemoryHigh=30G", command)
                self.assertIn("--property=MemorySwapMax=0", command)
                self.assertIn(pins["parent"]["sha256"], command)
                calls.append(dataset)
                if dataset == "SU":
                    raise ValueError("test failure retained")
                return {"status": resident_matrix.MEASURED}

            admitted = {"side_effect": matrix.NotAdmitted("test gate")} if reject else {
                "return_value": (pins, image, gate)}
            with (patch.object(matrix, "declaration", side_effect=declare),
                  patch.object(matrix, "wait_parent"),
                  patch.object(matrix, "check_memory", return_value=group),
                  patch.object(matrix, "runner_pins", return_value=[]),
                  patch.object(matrix, "unchanged"),
                  patch.object(matrix, "admit_parent", **admitted),
                  patch.object(resident_matrix, "run_child", side_effect=one)):
                report = matrix.queue(args)
                self.assertEqual(report, json.loads((args.output / "results.json").read_text()))
            return report, calls

    def test_no_board_children_until_joint_admission(self):
        report, calls = self.run_queue(reject=True)
        self.assertEqual(report["status"], "NOT_ADMITTED")
        self.assertEqual(report["board_children_started"], 0)
        self.assertEqual(calls, [])
        self.assertEqual([row["case"]["dataset"] for row in report["cases"]],
                         ["AU", "SU", "WK", "SO", "PK", "LJ", "LJ08"])

    def test_one_attempt_per_case_even_after_failure(self):
        report, calls = self.run_queue()
        self.assertEqual(report["status"], "MATRIX_NEEDS_REVIEW")
        self.assertEqual(report["board_children_started"], 7)
        self.assertEqual(calls, list(matrix.DATASETS))
        self.assertEqual(report["cases"][1]["status"], "FAILED_RETAINED")
        self.assertEqual(report["cases"][2]["status"], resident_matrix.MEASURED)
