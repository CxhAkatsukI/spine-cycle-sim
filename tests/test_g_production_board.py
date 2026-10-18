from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.production_board import experiments, supervisor as job
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution import study as board
from test_grasu_continuous_supervisor import INVOCATION, state


class ProductionBoardTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.original = self.root / "old.xclbin"
        self.original.write_text("synthetic original identity")
        self.output = self.root / "output"
        self.mock(board, "containment", return_value={})
        self.mock(job, "runner_pins", return_value=[])
        self.mock(job.gate, "snapshot", return_value={"pins": []})
        self.packet = self.mock(job.gate, "unchanged_packet")
        pin = job.identity(self.original)
        self.review = self.mock(job.gate, "review", return_value={"pins": [], "candidate": pin,
                                                                     "timing": {"report": pin}})
        # The supervisor freezes this terminal manifest only after route admission.
        (self.root / "manifest.json").write_text("{}")
        self.host = self.mock(experiments.native, "host_identity", return_value=({"contract": {"cases": [{}]}}, []))
        self.metadata = self.mock(experiments, "metadata_identity", return_value=({"contract": {"cases": [{}]}}, []))
        self.mock(experiments.handoff, "host_identity", return_value=({"contract": {"cases": [{}] * 9}}, []))
        self.states = self.mock(job, "service_state", return_value=state())
        self.sleep = self.mock(job.time, "sleep")
        self.mock(job, "current", return_value=self.root)
        self.mock(job, "other_builds", return_value=["bounded peer"])
        self.available = self.mock(job, "available_memory_bytes", return_value=120 * 1024**3)
        self.lease = self.mock(job, "Lease").return_value
        self.lease.held = False
        def reserve(available, peers, policy, *, commit):
            self.lease.held = commit
            return {"admitted": commit}
        self.lease.sample.side_effect = reserve
        self.launch = self.mock(board, "run", side_effect=self.matrix)

    def mock(self, owner, name, **options):
        return self.stack.enter_context(patch.object(owner, name, **options))

    def matrix(self, preflight, route, original, output, **options):
        self.assertTrue(self.lease.held)
        self.assertTrue(options["execute"])
        spec = options["experiment"]
        self.assertIs(spec.route_review, experiments.route.review)
        count = 9 if output.name == "resident_gr" else 1
        output.mkdir()
        result = {"status": spec.pass_status, "board_started": True, "board_correctness_measured": True,
                  "attempts": [{}] * (3 * count), **dict.fromkeys(board.CLAIMS, False)}
        (output / "results.json").write_text(json.dumps(result))
        return result

    def run_job(self, **options):
        return job.run(self.root, self.root, self.root, self.root, self.original, self.output,
                       route_unit="production-route.service", route_invocation=INVOCATION,
                       metadata_unit="metadata-host.service", metadata_invocation=INVOCATION, **options)

    def saved(self):
        return json.loads((self.output / "results.json").read_text())

    def test_both_exact_jobs_all_matrices_and_full_memory_lease_are_required(self):
        self.states.side_effect = [state("active"), state("active"), *([state()] * 8)]
        result = self.run_job()
        self.assertEqual(result["status"], job.PASS)
        self.assertEqual([row["name"] for row in result["matrices"]], ["native_g", "metadata_refresh", "resident_gr"])
        self.assertEqual(len(result["states"]), 2)
        self.assertEqual(self.launch.call_count, 3)
        self.assertTrue(result["board_correctness_measured"])
        self.assertTrue(all(result[key] is False for key in board.CLAIMS))
        self.lease.release.assert_called_once()
        self.sleep.assert_called_once()
        self.packet.assert_any_call(self.root, {"pins": []}, complete=True)

    def test_failed_restarted_or_missing_job_cannot_request_a_board(self):
        for changed in (state("failed"), state(InvocationID="b" * 32), state(LoadState="not-found"), state(ExecMainStatus="1")):
            with self.subTest(changed=changed):
                self.output = self.root / str(len(list(self.root.iterdir())))
                self.states.return_value = changed
                with self.assertRaises(ValueError): self.run_job()
                self.assertFalse(self.saved()["board_started"])
        self.review.assert_not_called()
        self.launch.assert_not_called()

    def test_late_metadata_failure_and_timing_rejection_stop_before_board(self):
        self.metadata.side_effect = ValueError("raw metadata evidence rejected")
        with self.assertRaisesRegex(ValueError, "metadata evidence"):
            self.run_job()
        self.launch.assert_not_called()
        self.output = self.root / "timing-rejection"
        self.metadata.side_effect = None
        self.review.side_effect = ValueError("final timing rejected")
        with self.assertRaisesRegex(ValueError, "timing rejected"):
            self.run_job()
        self.launch.assert_not_called()

    def test_running_jobs_timeout_without_programming(self):
        self.states.return_value = state("active")
        self.mock(job.time, "monotonic", side_effect=[0, 2])
        with self.assertRaises(TimeoutError): self.run_job(maximum_wait=1)
        self.review.assert_not_called()
        self.launch.assert_not_called()

    def test_conservative_watchdog_floor_defers_reservation_but_not_for_tool_exit(self):
        self.available.side_effect = [39 * 1024**3, 80 * 1024**3]
        self.run_job()
        self.assertEqual([call.kwargs["commit"] for call in self.lease.sample.call_args_list], [False, True])
        self.assertTrue(all(call.args[1] == ["bounded peer"] for call in self.lease.sample.call_args_list))
        self.sleep.assert_called_once()

    def test_partial_matrix_retained_and_later_matrices_not_run(self):
        def partial(*args, **kwargs):
            result = self.matrix(*args, **kwargs)
            result["attempts"].pop()
            return result
        self.launch.side_effect = partial
        with self.assertRaisesRegex(ValueError, "incomplete production"):
            self.run_job()
        self.assertEqual(self.launch.call_count, 1)
        self.assertTrue(self.saved()["board_started"])
        self.assertFalse(self.saved()["board_correctness_measured"])
        self.lease.release.assert_called_once()

    def test_failure_after_programming_retains_child_provenance(self):
        def fail(*args, **kwargs):
            output = args[3]
            output.mkdir()
            (output / "results.json").write_text(json.dumps({"status": "FAILED_RETAINED", "board_started": True}))
            raise ValueError("PMA mismatch")
        self.launch.side_effect = fail
        with self.assertRaisesRegex(ValueError, "PMA mismatch"):
            self.run_job()
        result = self.saved()
        self.assertTrue(result["board_started"])
        self.assertEqual(result["matrices"][0]["status"], "FAILED_RETAINED")

    def test_invalid_bounds_or_existing_output_rejected(self):
        for options in ({"device": True}, {"repeats": 2}, {"maximum_wait": float("inf")}, {"poll_seconds": 0}):
            with self.subTest(options=options), self.assertRaises(ValueError): self.run_job(**options)
        self.output.mkdir()
        with self.assertRaises(FileExistsError): self.run_job()
        self.launch.assert_not_called()


class ProductionExperimentTests(unittest.TestCase):
    def test_metadata_bdf_guard_and_case_adapter_preserve_original_contract(self):
        report = {"contract": {"case": experiments.metadata.CASE}, "pins": []}
        good = 'std::getenv("CONTINUOUS_G_EXPECT_BDF") CL_DEVICE_PCIE_BDF cl::Program(context'
        with patch.object(experiments.delivery, "validate", return_value=report), \
                patch.object(experiments, "identity", return_value={}), patch.object(Path, "read_text", return_value=good):
            result, _ = experiments.metadata_identity(Path("/preflight"))
        self.assertEqual(result["contract"]["cases"], [experiments.metadata.CASE])
        self.assertNotIn("cases", report["contract"])
        with patch.object(experiments.delivery, "validate", return_value=report), \
                patch.object(Path, "read_text", return_value="cl::Program(context " + good), self.assertRaises(ValueError):
            experiments.metadata_identity(Path("/preflight"))

    def test_shared_runner_uses_explicit_gate_without_weakening_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def reject(*args): raise ValueError("production gate rejected")
            spec = board.Experiment(lambda _: ({}, []), lambda *args: None, "unused", "synthetic", route_review=reject)
            with patch.object(board.runtime, "require_clean_environment"), \
                    patch.object(board.route, "review") as diagnostic, patch.object(board, "board_lease") as lease:
                with self.assertRaisesRegex(ValueError, "production gate rejected"):
                    board.run(root, root, root, root / "output", experiment=spec, execute=True)
                diagnostic.assert_not_called()
                lease.assert_not_called()


if __name__ == "__main__":
    unittest.main()
