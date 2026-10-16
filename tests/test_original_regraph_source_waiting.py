import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_build import waiting


class SourceMemoryQueueTests(unittest.TestCase):
    def invoke(self, root, states, *, wait=30, sleep=None, build_error=None,
               topology="original_example"):
        environment = root / "environment.json"
        if not environment.exists():
            environment.write_text('{"pins": []}')
        output = root / "queue"

        def build(*args, **kwargs):
            self.assertEqual(kwargs, {"topology": topology})
            if build_error:
                raise build_error
            destination = args[-1]
            destination.mkdir()
            (destination / "results.json").write_text('{"status": "ROUTED_AWAITING_BOARD"}')
            return {"status": "ROUTED_AWAITING_BOARD"}

        with patch.object(waiting, "current", return_value=root / "cgroup"), \
                patch.object(waiting, "verify") as guard, \
                patch.object(waiting.execution, "prerequisites", return_value=[]), \
                patch.object(waiting.execution, "runner_pins", return_value=[]), \
                patch.object(waiting.execution, "run", side_effect=build) as runner, \
                patch.object(waiting, "available_memory_bytes", return_value=128 * 1024**3), \
                patch.object(waiting, "other_builds", return_value=["123 vivado"]), \
                patch.object(waiting, "Lease") as lease, \
                patch.object(waiting.time, "monotonic", side_effect=[0, 0, 31]), \
                patch.object(waiting.time, "sleep", side_effect=sleep) as sleeper:
            lease.return_value.sample.side_effect = states
            try:
                result = waiting.run(root, root / "author", root / "audit", root / "control",
                                     environment, output, wait_seconds=wait, topology=topology)
            except (ValueError, TimeoutError, RuntimeError):
                result = json.loads((output / "queue.json").read_text())
            return result, runner.call_count, lease.return_value.sample.call_args_list, sleeper.call_count

    def test_admits_immediately_even_when_another_fpga_tool_is_running(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, samples, sleeps = self.invoke(Path(directory), [{"admitted": True}])
            self.assertEqual(result["status"], "ROUTED_AWAITING_BOARD")
            self.assertEqual((calls, sleeps, len(samples)), (1, 0, 1))
            self.assertFalse(samples[0].kwargs["commit"])
            self.assertFalse(result["board_programmed"])

    def test_waits_for_budget_then_starts_once_without_holding_a_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, samples, sleeps = self.invoke(
                Path(directory), [{"admitted": False}, {"admitted": True}])
            self.assertEqual((calls, sleeps, result["samples"]), (1, 1, 2))
            self.assertTrue(all(not call.kwargs["commit"] for call in samples))

    def test_a4_queue_preserves_the_declared_topology_when_starting(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, _, _ = self.invoke(Path(directory), [{"admitted": True}], topology="a4")
            self.assertEqual((result["configuration"], result["little"], result["big"]), ("a4", 4, 0))
            self.assertEqual(calls, 1)

    def test_unbounded_or_insufficient_peer_budget_never_starts_compiler(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, _, _ = self.invoke(Path(directory), [
                {"admitted": False, "reservations": [{"bounded": False}]}, {"admitted": False}])
            self.assertEqual(result["status"], "FAILED_RETAINED")
            self.assertEqual(calls, 0)
            self.assertIn("deadline", result["errors"][0])

    def test_changed_environment_while_waiting_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, calls, _, _ = self.invoke(root, [{"admitted": False}],
                sleep=lambda _: (root / "environment.json").write_text('{"pins": [], "changed": true}'))
            self.assertEqual(result["status"], "FAILED_RETAINED")
            self.assertEqual(calls, 0)
            self.assertIn("changed", result["errors"][0])

    def test_resource_race_or_real_build_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, _, sleeps = self.invoke(Path(directory), [{"admitted": True}],
                                                   build_error=RuntimeError("second admission failed"))
            self.assertEqual((result["status"], calls, sleeps), ("FAILED_RETAINED", 1, 0))

    def test_invalid_wait_and_existing_output_are_rejected_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "existing"
            output.mkdir()
            for value in (-1, 0, 86401, True, 1.5):
                with self.assertRaises(ValueError):
                    waiting.run(root, root, root, root, root, output, wait_seconds=value)
            with self.assertRaises(FileExistsError):
                waiting.run(root, root, root, root, root, output, wait_seconds=30)
            self.assertEqual(list(output.iterdir()), [])
