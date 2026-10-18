from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import continuation as job
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote.transport import Remote
from test_grasu_continuous_supervisor import INVOCATION, state


class RemoteContinuationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root / "manifest.json").write_text(json.dumps({"pins": []}))
        self.original = self.root / "original.xclbin"
        self.original.write_text("synthetic original")
        self.output = self.root / "output"
        self.remote = Remote("user@example", 23333, Path("/runner"), Path("/capsule"), Path("/attempt"),
                             Path("/returned"), "remote.service", INVOCATION)
        self.mock(job.qualification.board, "containment", return_value={})
        self.mock(job.production, "candidate")
        self.mock(job, "runner_pins", return_value=[])
        self.mock(job.experiments, "plans", return_value=[])
        self.states = self.mock(Remote, "state", return_value=state())
        self.seal = self.mock(Remote, "seal", return_value="a" * 64)
        self.transfer = self.mock(Remote, "transfer")
        self.verify = self.mock(job.delivery, "verify")
        self.qualify = self.mock(job.qualification, "run", side_effect=self.qualified)
        self.sleep = self.mock(job.time, "sleep")

    def mock(self, owner, name, **options):
        return self.stack.enter_context(patch.object(owner, name, **options))

    def qualified(self, *args, **kwargs):
        output = args[5]
        output.mkdir()
        result = {"status": job.qualification.PASS, "board_started": True, "board_correctness_measured": True}
        (output / "results.json").write_text(json.dumps(result))
        return result

    def run_job(self, **options):
        return job.run(self.remote, self.root, self.root, self.root, self.root, self.original, self.output, **options)

    def saved(self):
        return json.loads((self.output / "results.json").read_text())

    def test_exact_terminal_remote_then_verified_transport_and_qualification(self):
        self.states.side_effect = [state("active"), state(), state()]
        result = self.run_job()
        self.assertEqual(result["status"], job.qualification.PASS)
        self.assertEqual(len(result["states"]), 2)
        self.assertTrue(result["board_correctness_measured"])
        self.assertTrue(all(result[key] is False for key in job.capsule.FLAGS))
        self.sleep.assert_called_once()
        self.seal.assert_called_once()
        self.verify.assert_called_once_with(self.output / "returned", "a" * 64)
        self.assertEqual(self.qualify.call_args.kwargs["receipt_sha256"], "a" * 64)

    def test_failed_changed_or_missing_remote_prevents_transport_and_board(self):
        for changed in (state("failed"), state(InvocationID="b" * 32), state(LoadState="not-found")):
            with self.subTest(changed=changed):
                self.output = self.root / str(len(list(self.root.iterdir())))
                self.states.return_value = changed
                with self.assertRaises(ValueError):
                    self.run_job()
                self.assertFalse(self.saved()["board_started"])
        self.seal.assert_not_called()
        self.transfer.assert_not_called()
        self.qualify.assert_not_called()

    def test_running_timeout_changed_local_input_or_bad_transport_prevents_board(self):
        self.states.return_value = state("active")
        with patch.object(job.time, "monotonic", side_effect=[0, 2]), self.assertRaises(TimeoutError):
            self.run_job(maximum_wait=1)
        self.seal.assert_not_called()
        self.output = self.root / "changed-input"
        self.states.return_value = state()

        def change_input():
            self.original.write_text("changed")
            return "a" * 64

        self.seal.side_effect = change_input
        with self.assertRaisesRegex(ValueError, "changed"):
            self.run_job()
        self.qualify.assert_not_called()
        self.output = self.root / "bad-transport"
        self.seal.side_effect = None
        self.verify.side_effect = ValueError("return hash mismatch")
        with self.assertRaisesRegex(ValueError, "return hash"):
            self.run_job()
        self.qualify.assert_not_called()

    def test_child_failure_preserves_programming_provenance(self):
        def fail(*args, **kwargs):
            output = args[5]
            output.mkdir()
            (output / "results.json").write_text(json.dumps({"status": "FAILED_RETAINED", "board_started": True}))
            raise ValueError("metadata mismatch")

        self.qualify.side_effect = fail
        with self.assertRaisesRegex(ValueError, "metadata mismatch"):
            self.run_job()
        report = self.saved()
        self.assertTrue(report["board_started"])
        self.assertFalse(report["board_correctness_measured"])


class RemoteTransportTests(unittest.TestCase):
    def remote(self, **options):
        fields = {"target": "user@example", "port": 23333, "runner": Path("/runner"), "capsule": Path("/capsule"),
                  "attempt": Path("/attempt"), "returned": Path("/returned"), "unit": "remote.service",
                  "invocation": INVOCATION, **options}
        return Remote(**fields)

    def test_bounded_batchmode_quoted_command_and_strict_service_fields(self):
        remote = self.remote()
        text = "\n".join(key + "=" + value for key, value in state().items())
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, text, "")) as run:
            self.assertEqual(remote.state(), state())
            self.assertEqual(run.call_args.kwargs["timeout"], 30)
            self.assertIn("BatchMode=yes", run.call_args.args[0])
        with patch.object(Remote, "command", return_value=text + "\nLoadState=loaded"), self.assertRaises(ValueError):
            remote.state()
        with patch.object(Remote, "command", return_value="a" * 64) as command:
            self.assertEqual(remote.seal(), "a" * 64)
            self.assertIn("--property=MemoryMax=4G", command.call_args.args[0])
            self.assertIn("--invocation", command.call_args.args[0])
        with patch.object(Remote, "command", return_value="queued"), self.assertRaises(ValueError):
            remote.seal()

    def test_invalid_endpoint_paths_and_identity_rejected(self):
        for options in ({"target": "user@example;rm"}, {"port": True}, {"runner": Path("relative")},
                        {"attempt": Path("/a/../b")}, {"unit": "remote;bad.service"}, {"invocation": "unknown"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.remote(**options)


if __name__ == "__main__":
    unittest.main()
