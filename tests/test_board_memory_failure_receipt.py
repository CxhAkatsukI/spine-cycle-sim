"""Failed board processes retain diagnostics without becoming measured pairs."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import (
    guarded_process, memory_policy,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import runtime


class BoardMemoryFailureReceiptTests(unittest.TestCase):
    def execute(self, root, guard):
        with memory_policy.scope(memory_policy.ARC), \
                patch.object(runtime, "check_memory", return_value=root), \
                patch.object(runtime.subprocess, "run", return_value=Mock(returncode=1)), \
                patch.object(guarded_process, "run", guard):
            return runtime.execute(["owned"], root, "spine", 123, Path("/dev/fake"), "fake")

    def test_stop_receipt_preserves_logs_cgroup_pressure_and_original_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "memory.pressure").write_text("some avg10=0.00\nfull avg10=0.00\n")
            (root / "memory.peak").write_text("1234\n")
            failure = MemoryError("system pressure")
            failure.memory_guard = dict(status="ABORTED", checks=2)
            with self.assertRaises(MemoryError) as raised:
                self.execute(root, Mock(side_effect=failure))
            self.assertIs(raised.exception, failure)
            pin = failure.memory_guard_receipt
            self.assertEqual(runtime.identity(pin["path"]), pin)
            receipt = json.loads(Path(pin["path"]).read_text())
            self.assertEqual(receipt["status"], "FAILED_RETAINED")
            self.assertEqual(receipt["memory_guard"], failure.memory_guard)
            self.assertEqual(len(receipt["logs"]), 2)
            self.assertEqual(receipt["cgroup_after"]["memory.peak"], "1234\n")
            self.assertEqual(receipt["cgroup_before"]["memory.pressure"],
                             receipt["cgroup_after"]["memory.pressure"])
            self.assertIn("error", receipt["cgroup_after"]["memory.events"])

    def test_nonzero_exit_is_failed_even_when_memory_guard_completes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(RuntimeError, "failed \\(9\\)") as raised:
                self.execute(root, Mock(return_value=(9, dict(status="COMPLETED"))))
            receipt = json.loads(Path(raised.exception.memory_guard_receipt["path"]).read_text())
            self.assertEqual(receipt["status"], "FAILED_RETAINED")
            self.assertEqual(receipt["memory_guard"]["status"], "COMPLETED")

    def test_success_remains_a_success_without_failure_sidecar(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            row = self.execute(root, Mock(return_value=(0, dict(status="COMPLETED"))))
            self.assertEqual(row["memory_guard"]["status"], "COMPLETED")
            self.assertFalse((root / "spine.memory-failure.json").exists())

    def test_receipt_io_failure_does_not_replace_original_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            failure = MemoryError("pressure")
            with patch.object(runtime, "save", side_effect=OSError("disk full")), \
                    self.assertRaises(MemoryError) as raised:
                self.execute(Path(temporary), Mock(side_effect=failure))
            self.assertIs(raised.exception, failure)
            self.assertIn("disk full", failure.__notes__[0])


if __name__ == "__main__":
    unittest.main()
