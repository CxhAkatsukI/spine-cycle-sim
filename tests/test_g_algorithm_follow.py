from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build import follow as job
from test_grasu_continuous_supervisor import INVOCATION, state


class AlgorithmFollowTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root / "sources.json").write_text("synthetic sources")
        self.output = self.root / "attempt"
        self.remote = job.AlgorithmRemote("user@example", 23333, Path("/runner"), Path("/sources"),
            Path("/route"), Path("/returned"), "route.service", INVOCATION, Path("/compile"))
        self.mock(job, "current", return_value=Path("/synthetic-cgroup"))
        self.mock(job, "verify", return_value={})
        self.mock(job.inputs, "verify", return_value={"integration_revision": "a" * 40})
        self.mock(job, "runner_pins", return_value=[])
        self.states = self.mock(job.AlgorithmRemote, "state", return_value=state())
        self.seal = self.mock(job.AlgorithmRemote, "seal", return_value="b" * 64)
        self.transfer = self.mock(job.AlgorithmRemote, "transfer")
        self.receipt = self.mock(job.artifacts, "verify", return_value={"algorithm": "connected_components",
            "integration_revision": "a" * 40, "unit": "route.service", "invocation": INVOCATION})
        self.admit = self.mock(job.admission, "review", side_effect=self.admitted)
        self.sleep = self.mock(job.time, "sleep")

    def mock(self, owner, name, **options):
        return self.stack.enter_context(patch.object(owner, name, **options))

    def admitted(self, returned, sources, output, **options):
        output.mkdir()
        result = {"status": "ALGORITHM_ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD",
                  "algorithm": "connected_components"}
        (output / "summary.json").write_text(json.dumps(result))
        return result

    def run_job(self, **options):
        return job.run(self.remote, self.root, "connected_components", self.output, **options)

    def saved(self):
        return json.loads((self.output / "results.json").read_text())

    def test_exact_terminal_service_then_receipt_and_strict_admission(self):
        self.states.side_effect = [state("active"), state(), state()]
        result = self.run_job()
        self.assertEqual(result["status"], job.PASS)
        self.assertEqual(len(result["states"]), 2)
        self.assertFalse(result["board_requested"])
        self.assertTrue(all(result[key] is False for key in job.artifacts.FLAGS))
        self.sleep.assert_called_once()
        self.seal.assert_called_once()
        self.receipt.assert_called_once_with(self.output / "returned", "b" * 64)
        self.assertEqual(self.admit.call_args.kwargs["receipt_sha256"], "b" * 64)

    def test_failed_missing_changed_remote_or_timeout_cannot_transfer(self):
        for index, changed in enumerate((state("failed"), state(InvocationID="c" * 32),
                                          state(LoadState="not-found"))):
            self.output = self.root / str(index)
            self.states.return_value = changed
            with self.assertRaises(ValueError):
                self.run_job()
            self.assertEqual(self.saved()["status"], "FAILED_RETAINED")
        self.output = self.root / "timeout"
        self.states.return_value = state("active")
        with patch.object(job.time, "monotonic", side_effect=[0, 2]), self.assertRaises(TimeoutError):
            self.run_job(maximum_wait=1)
        self.seal.assert_not_called()
        self.transfer.assert_not_called()

    def test_compile_and_route_lifetime_can_be_followed_without_relaxing_admission(self):
        result = self.run_job(maximum_wait=job.MAXIMUM_WAIT_SECONDS)
        self.assertEqual(result["maximum_wait_seconds"], 270000)
        self.assertEqual(result["status"], job.PASS)
        self.admit.assert_called_once()
        self.assertTrue(all(result[key] is False for key in job.artifacts.FLAGS))

    def test_receipt_scope_hash_or_post_transfer_service_mismatch_rejected(self):
        correct = self.receipt.return_value.copy()
        for index, change in enumerate(({"algorithm": "full_pagerank"}, {"integration_revision": "c" * 40},
                                         {"unit": "other.service"}, {"invocation": "c" * 32})):
            self.output = self.root / str(index)
            self.receipt.return_value = {**correct, **change}
            with self.assertRaisesRegex(ValueError, "returned algorithm"):
                self.run_job()
        self.admit.assert_not_called()
        self.output = self.root / "bad-hash"
        self.receipt.side_effect = ValueError("receipt hash mismatch")
        with self.assertRaisesRegex(ValueError, "receipt hash"):
            self.run_job()
        self.receipt.side_effect = None
        self.receipt.return_value = {"algorithm": "connected_components", "integration_revision": "a" * 40,
                                    "unit": "route.service", "invocation": INVOCATION}
        self.output = self.root / "changed-service"
        self.states.side_effect = [state(), state(InvocationID="c" * 32)]
        with self.assertRaises(ValueError):
            self.run_job()
        self.admit.assert_not_called()

    def test_changed_local_source_or_rejected_metadata_cannot_pass(self):
        def mutate():
            (self.root / "sources.json").write_text("changed source manifest")
            return "b" * 64

        self.seal.side_effect = mutate
        with self.assertRaisesRegex(ValueError, "changed"):
            self.run_job()
        self.admit.assert_not_called()
        self.output = self.root / "bad-admission"
        self.seal.side_effect = None
        self.admit.side_effect = ValueError("clock mismatch")
        with self.assertRaisesRegex(ValueError, "clock mismatch"):
            self.run_job()
        self.assertFalse(self.saved()["board_requested"])


class AlgorithmTransportTests(unittest.TestCase):
    def remote(self, **changes):
        fields = {"target": "user@example", "port": 23333, "runner": Path("/runner"),
                  "capsule": Path("/sources"), "attempt": Path("/route"), "returned": Path("/returned"),
                  "unit": "route.service", "invocation": INVOCATION, "compilation": Path("/compile"), **changes}
        return job.AlgorithmRemote(**fields)

    def test_algorithm_sealer_is_separate_bounded_and_explicit(self):
        with patch.object(job.AlgorithmRemote, "command", return_value="b" * 64) as command:
            self.assertEqual(self.remote().seal(), "b" * 64)
            argv = command.call_args.args[0]
            self.assertIn("--property=MemoryMax=4G", argv)
            self.assertIn("--property=MemorySwapMax=0", argv)
            self.assertEqual(argv[argv.index("--compilation") + 1], Path("/compile"))
            self.assertIn("seal-route", argv)
        with patch.object(job.AlgorithmRemote, "command", return_value="queued"), self.assertRaises(ValueError):
            self.remote().seal()

    def test_unsafe_paths_and_unbounded_waits_rejected(self):
        for path in (Path("relative"), Path("/a/../b")):
            with self.assertRaises(ValueError):
                self.remote(compilation=path)
        for options in ({"maximum_wait": True}, {"maximum_wait": 0}, {"maximum_wait": 270001},
                        {"poll_seconds": float("nan")}, {"poll_seconds": 0}):
            with self.assertRaises(ValueError):
                job.run(self.remote(), Path("/sources"), "connected_components", Path("/unused"), **options)


if __name__ == "__main__":
    unittest.main()
