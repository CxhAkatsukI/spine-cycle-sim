from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution import supervisor as job

INVOCATION = "a" * 32


def state(active="inactive", **changes):
    return {"LoadState": "loaded", "ActiveState": active, "SubState": "dead" if active == "inactive" else "running",
            "InvocationID": INVOCATION, "Result": "success", "MainPID": "0" if active == "inactive" else "123",
            "ExecMainStatus": "0", **changes}


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.route = self.root / "route"
        self.route.mkdir()
        (self.route / "manifest.json").write_text('{"pins": []}')
        self.original = self.root / "old.xclbin"
        self.original.write_text("immutable reference")
        self.output = self.root / "supervisor"
        self.mock(job.board, "containment", return_value={})
        self.mock(job, "runner_pins", return_value=[])
        self.mock(job.board, "host_identity", return_value=({"contract": {"cases": list(range(6))}}, []))
        self.mock(job.handoff, "host_identity", return_value=({"contract": {"cases": list(range(9))}}, []))
        pin = job.identity(self.original)
        self.review = self.mock(job.board.route, "review", return_value={"pins": [], "candidate": pin,
                                                                          "timing": {"report": pin}})
        self.states = self.mock(job, "service_state", return_value=state())
        self.sleep = self.mock(job.time, "sleep")
        self.g = self.mock(job.board, "run", side_effect=self.matrix(job.board.PASS, 6))
        self.gr = self.mock(job.handoff, "run", side_effect=self.matrix(job.handoff.BOARD_PASS, 9))

    def mock(self, owner, name, **options):
        return self.stack.enter_context(patch.object(owner, name, **options))

    def matrix(self, status, count):
        def execute(preflight, route, original, output, **options):
            self.assertTrue(options["execute"])
            self.assertEqual(options["device"], 0)
            self.assertEqual(options["repeats"], 3)
            output.mkdir()
            report = {"status": status, "board_started": True, "board_correctness_measured": True,
                      "attempts": [{}] * (3 * count), **dict.fromkeys(job.board.CLAIMS, False)}
            (output / "results.json").write_text(json.dumps(report))
            return report
        return execute

    def run_job(self, **options):
        return job.run(self.root, self.root, self.route, self.original, self.output,
                       route_unit="frozen-route.service", route_invocation=INVOCATION, **options)

    def saved(self):
        return json.loads((self.output / "results.json").read_text())

    def test_running_service_success_is_not_completion_and_both_matrices_are_required(self):
        self.states.side_effect = [state("active"), state(), state(), state()]
        result = self.run_job()
        self.assertEqual(result["status"], job.PASS)
        self.assertEqual(len(result["route_states"]), 2)
        self.sleep.assert_called_once()
        self.review.assert_called_once()
        self.g.assert_called_once()
        self.gr.assert_called_once()
        self.assertTrue(result["board_correctness_measured"])
        self.assertTrue(all(result[key] is False for key in job.board.CLAIMS))

    def test_remain_after_exit_is_terminal_only_with_success_and_no_main_process(self):
        retained = state("active", SubState="exited", MainPID="0")
        self.assertTrue(job.route_finished(retained, INVOCATION))
        for change in ({"MainPID": "123"}, {"ExecMainStatus": "1"}, {"Result": "signal"},
                       {"InvocationID": "b" * 32}, {"LoadState": "not-found"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                job.route_finished({**retained, **change}, INVOCATION)
        self.assertFalse(job.route_finished(state("active"), INVOCATION))
        self.assertFalse(job.route_finished(state("deactivating"), INVOCATION))

    def test_failed_disappeared_or_restarted_route_cannot_request_a_board(self):
        for changed in (state("failed"), state(Result="signal"), state(InvocationID="b" * 32),
                        state(LoadState="not-found"), state(ExecMainStatus="1"), state(MainPID="123")):
            with self.subTest(state=changed):
                self.output = self.root / str(len(list(self.root.iterdir())))
                self.states.return_value = changed
                with self.assertRaises(ValueError):
                    self.run_job()
                self.assertFalse(self.saved()["board_started"])
                self.assertEqual(self.saved()["status"], "FAILED_RETAINED")
        self.review.assert_not_called()
        self.g.assert_not_called()
        self.gr.assert_not_called()

    def test_route_wait_timeout_stops_without_board_request(self):
        self.states.return_value = state("active")
        self.mock(job.time, "monotonic", side_effect=[0, 2])
        with self.assertRaises(TimeoutError):
            self.run_job(maximum_wait=1)
        self.review.assert_not_called()
        self.g.assert_not_called()

    def test_timing_rejection_stops_before_board_request(self):
        self.review.side_effect = ValueError("setup timing failed")
        with self.assertRaisesRegex(ValueError, "timing failed"):
            self.run_job()
        self.assertFalse(self.saved()["board_started"])
        self.g.assert_not_called()
        self.gr.assert_not_called()

    def test_frozen_input_change_while_waiting_stops(self):
        self.states.return_value = state("active")
        self.sleep.side_effect = lambda _: self.original.write_text("changed")
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.run_job()
        self.review.assert_not_called()
        self.g.assert_not_called()

    def test_incomplete_host_scope_and_missing_containment_stop(self):
        self.mock(job.board, "host_identity", return_value=({"contract": {"cases": []}}, []))
        with self.assertRaisesRegex(ValueError, "six-input"):
            self.run_job()
        self.states.assert_not_called()
        self.g.assert_not_called()
        self.output = self.root / "unbounded"
        self.mock(job.board, "containment", side_effect=ValueError("unbounded"))
        with self.assertRaisesRegex(ValueError, "unbounded"):
            self.run_job()
        self.g.assert_not_called()

    def test_g_failure_retains_attempted_board_state_and_does_not_run_handoff(self):
        def fail(*args, **options):
            output = args[3]
            output.mkdir()
            (output / "results.json").write_text(json.dumps({"status": "FAILED_RETAINED", "board_started": True}))
            raise ValueError("board output mismatch")
        self.g.side_effect = fail
        with self.assertRaisesRegex(ValueError, "output mismatch"):
            self.run_job()
        result = self.saved()
        self.assertTrue(result["board_started"])
        self.assertFalse(result["board_correctness_measured"])
        self.assertEqual(result["matrices"][0]["status"], "FAILED_RETAINED")
        self.gr.assert_not_called()

    def test_partial_matrix_is_not_promoted_to_pass(self):
        execute = self.matrix(job.board.PASS, 6)
        def partial(*args, **options):
            result = execute(*args, **options)
            result["attempts"].pop()
            return result
        self.g.side_effect = partial
        with self.assertRaisesRegex(ValueError, "declared correctness scope"):
            self.run_job()
        self.gr.assert_not_called()
        self.assertFalse(self.saved()["board_correctness_measured"])

    def test_service_identity_is_rechecked_before_each_matrix(self):
        self.states.side_effect = [state(), state(), state(InvocationID="b" * 32)]
        with self.assertRaisesRegex(ValueError, "invocation changed"):
            self.run_job()
        self.g.assert_called_once()
        self.gr.assert_not_called()
        self.assertTrue(self.saved()["board_started"])

    def test_invalid_inputs_and_existing_output_are_rejected(self):
        for options in ({"maximum_wait": float("nan")}, {"poll_seconds": 0}, {"device": True}, {"repeats": 2}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_job(**options)
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            self.run_job()
        self.g.assert_not_called()

    def test_production_runner_pin_collection_includes_handoff_and_supervisor(self):
        self.stack.close()
        paths = {pin["path"] for pin in job.runner_pins()}
        self.assertIn(str(Path(job.__file__).resolve()), paths)
        self.assertIn(str(Path(job.handoff.__file__).resolve()), paths)

    def test_systemd_properties_are_complete_unique_and_quiet(self):
        self.stack.close()
        text = "\n".join(key + "=" + value for key, value in state().items())
        with patch.object(job.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout=text, stderr="")) as read:
            self.assertEqual(job.service_state("required.service"), state())
            self.assertEqual(read.call_args.kwargs["timeout"], 10)
        for stdout, stderr, code in ((text + "\nResult=success", "", 0), ("ActiveState=active", "", 0),
                                     (text, "warning", 0), (text, "", 1), (text + "\nmalformed", "", 0)):
            with self.subTest(stderr=stderr, code=code), patch.object(job.subprocess, "run",
                    return_value=SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)), \
                    self.assertRaises(ValueError):
                job.service_state("required.service")


if __name__ == "__main__":
    unittest.main()
