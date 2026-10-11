"""Exercise the new CLI's exit and pinning contract without invoking a compiler."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment import route_execution
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route import admit
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity

OWNER = route_execution.__name__
ROUTE = "spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route"


class EmptySegmentRouteExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.build, self.production, self.output = (self.root / name for name in ("build", "production", "route"))
        self.frozen = self.root / "frozen_input"
        self.frozen.write_bytes(b"frozen input")
        self.wrapper = identity(Path(route_execution.__file__))
        self.extra_pins = []
        self.prepare = self.start_patch(OWNER + ".prepare", side_effect=self.prepare_fixture)
        self.memory = self.start_patch(ROUTE + ".available_memory_bytes", return_value=64 * 1024**3)
        self.admit = self.start_patch(OWNER + ".admit", side_effect=self.admit_fixture)
        self.execute = self.start_patch(OWNER + ".execute_route", return_value={
            "status": "LINK_PASS_AWAITING_TIMING_AND_BOARD", "inputs_unchanged": True})

    def start_patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def prepare_fixture(self, build, production, output):
        self.assertEqual((build, production, output), (self.build, self.production, self.output))
        output.mkdir()
        manifest = {"status": "PREPARED_NOT_ROUTED", "pins": [identity(self.frozen), *self.extra_pins],
                    "command": ["mock-v++", "--link"], "tree_memory_gib": 40, "reserve_gib": 16,
                    "timeout_seconds": 14400}
        atomic_write_json(output / "manifest.json", manifest)
        return manifest

    def admit_fixture(self, output):
        manifest = self.read("manifest.json")
        self.assertEqual(manifest["execution_wrapper"], self.wrapper)
        self.assertIn(self.wrapper, manifest["pins"])
        self.assertEqual(manifest["environment_contract"], "inherited_not_shell_replayed_or_validated")
        return admit(output)

    def read(self, name):
        return json.loads((self.output / name).read_text())

    def run_route(self, *, execute=False):
        return route_execution.run(self.build, self.production, self.output, execute=execute)

    def test_prepare_only_pins_wrapper_before_admission_without_execution(self):
        result = self.run_route()
        self.assertEqual((result["status"], result["exit_code"]), ("MEMORY_ADMITTED_NOT_STARTED", 0))
        self.assertFalse(result["execution_requested"])
        self.assertFalse(result["route_started"])
        self.assertEqual(self.read("execution.json"), result)
        self.assertFalse(self.read("manifest.json")["execution_requested"])
        self.assertIn(identity(self.frozen), self.read("manifest.json")["pins"])
        self.execute.assert_not_called()

    def test_prepare_only_rejection_is_recorded_but_not_an_execution_failure(self):
        self.memory.return_value = 51 * 1024**3
        result = self.run_route()
        self.assertEqual((result["status"], result["exit_code"]), ("ADMISSION_REJECTED_NOT_STARTED", 0))
        self.assertEqual(self.read("admission.json")["required_bytes"], 56 * 1024**3)
        self.assertFalse((self.output / "failure.json").exists())
        self.execute.assert_not_called()

    def test_requested_execution_rejection_is_nonzero_and_never_launches(self):
        self.memory.return_value = 51 * 1024**3
        result = self.run_route(execute=True)
        self.assertEqual((result["status"], result["exit_code"]), ("ADMISSION_REJECTED_NOT_STARTED", 2))
        self.assertTrue(result["execution_requested"])
        self.assertFalse(result["route_started"])
        self.assertEqual(self.read("execution.json"), result)
        self.assertFalse((self.output / "route.resources.json").exists())
        self.execute.assert_not_called()

    def test_link_pass_is_success_but_not_timing_admission(self):
        result = self.run_route(execute=True)
        self.assertEqual((result["status"], result["exit_code"]), ("LINK_PASS_AWAITING_TIMING_AND_BOARD", 0))
        self.assertTrue(result["execution_requested"])
        self.assertEqual(self.read("execution.json"), result)
        self.assertFalse((self.output / "failure.json").exists())
        self.execute.assert_called_once_with(self.output)

    def test_link_failure_preserves_returned_result_and_existing_raw_summary(self):
        raw = {"status": "LINK_FAILED", "resources": {"exit_code": 1, "stop_reason": "process_exit"},
               "inputs_unchanged": True, "xclbin": None}
        def failed(output):
            atomic_write_json(output / "summary.json", raw)
            return raw
        self.execute.side_effect = failed
        result = self.run_route(execute=True)
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(self.read("failure.json"), result)
        self.assertEqual(self.read("execution.json"), result)
        self.assertEqual(self.read("summary.json"), raw)

    def test_resource_failure_with_zero_child_exit_is_nonzero(self):
        self.execute.return_value = {"status": "LINK_FAILED", "resources": {
            "exit_code": 0, "stop_reason": "tree_rss_budget"}}
        result = self.run_route(execute=True)
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(self.read("failure.json")["resources"]["stop_reason"], "tree_rss_budget")

    def test_timeout_is_nonzero_and_preserved(self):
        self.execute.return_value = {"status": "LINK_FAILED", "resources": {
            "exit_code": -9, "stop_reason": "timeout"}}
        result = self.run_route(execute=True)
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(self.read("failure.json")["resources"]["stop_reason"], "timeout")

    def test_unknown_execution_status_fails_closed(self):
        self.execute.return_value = {"status": "UNEXPECTED"}
        result = self.run_route(execute=True)
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(self.read("failure.json"), result)

    def test_execution_exception_is_persisted_without_claiming_a_launch(self):
        self.execute.side_effect = RuntimeError("insufficient memory at launch")
        result = self.run_route(execute=True)
        self.assertEqual((result["status"], result["exit_code"]), ("ROUTE_EXECUTION_FAILED", 1))
        self.assertEqual(result["error"], "insufficient memory at launch")
        self.assertIsNone(result["route_started"])
        self.assertEqual(self.read("failure.json"), result)
        self.assertEqual(self.read("execution.json"), result)

    def test_admission_exception_is_persisted_without_execution(self):
        self.admit.side_effect = ValueError("changed input")
        result = self.run_route(execute=True)
        self.assertEqual((result["status"], result["exit_code"]), ("ROUTE_PREPARATION_FAILED", 1))
        self.assertEqual(result["stage"], "admission")
        self.assertFalse(result["route_started"])
        self.assertEqual(self.read("failure.json"), result)
        self.execute.assert_not_called()

    def test_matching_existing_wrapper_pin_is_not_duplicated(self):
        self.extra_pins = [self.wrapper]
        self.run_route()
        self.assertEqual(self.read("manifest.json")["pins"].count(self.wrapper), 1)

    def test_conflicting_wrapper_pin_fails_before_admission(self):
        self.extra_pins = [{**self.wrapper, "sha256": "wrong"}]
        result = self.run_route(execute=True)
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["stage"], "pinning")
        self.assertEqual(self.read("failure.json"), result)
        self.admit.assert_not_called()
        self.execute.assert_not_called()

    def test_existing_output_is_never_modified(self):
        self.output.mkdir()
        previous = self.output / "failure.json"
        previous.write_bytes(b"preserved previous failure")
        with self.assertRaises(FileExistsError):
            self.run_route(execute=True)
        self.assertEqual(previous.read_bytes(), b"preserved previous failure")
        self.admit.assert_not_called()
        self.execute.assert_not_called()

    def cli(self, execute=False):
        argv = ["--build", str(self.build), "--production", str(self.production), "--output", str(self.output)]
        if execute:
            argv.append("--execute")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = route_execution.main(argv)
        return code, json.loads(stdout.getvalue())

    def test_cli_returns_nonzero_for_link_failed(self):
        self.execute.return_value = {"status": "LINK_FAILED"}
        code, result = self.cli(execute=True)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "LINK_FAILED")

    def test_cli_returns_distinct_nonzero_for_requested_admission_refusal(self):
        self.memory.return_value = 51 * 1024**3
        code, result = self.cli(execute=True)
        self.assertEqual(code, 2)
        self.assertFalse(result["route_started"])
        self.execute.assert_not_called()

    def test_cli_prepare_only_remains_successful_without_launch(self):
        code, result = self.cli()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "MEMORY_ADMITTED_NOT_STARTED")
        self.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
