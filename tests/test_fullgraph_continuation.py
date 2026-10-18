from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import continuation as job
from test_grasu_continuous_supervisor import INVOCATION, state


class FullgraphContinuationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.preflight = self.root / "preflight"
        self.preflight.mkdir()
        (self.preflight / "results.json").write_text(json.dumps({"status": job.analysis.PASS}))
        self.requests = []
        for algorithm in job.preparation.ALGORITHMS:
            root = self.root / algorithm
            root.mkdir()
            admission = root / ("board/routed_admission/summary.json" if algorithm == "weighted_sssp" else
                                "admission/summary.json")
            admission.parent.mkdir(parents=True)
            admission.write_text(json.dumps({"synthetic": algorithm}))
            report = {"errors": [], "status": job.follow.PASS, "algorithm": algorithm,
                      "admission": job.digest_identity(admission)}
            if algorithm == "weighted_sssp":
                board_report = root / "board/results.json"
                board_report.write_text(json.dumps({"admission": json.loads(admission.read_text())}))
                report.update(status=job.qualification.PASS, board_correctness_measured=True,
                              board_report=job.digest_identity(board_report))
            (root / "results.json").write_text(json.dumps(report))
            self.requests.append(job.Request(algorithm, algorithm + ".service", INVOCATION, root, admission,
                                            0 if algorithm == "weighted_sssp" else 1))
        self.output = self.root / "output"
        self.states = self.mock(job, "service_state", return_value=state())
        self.mock(job, "runner_pins", return_value=[])
        self.board = self.mock(job.board_study, "run", side_effect=self.board_done)
        self.sleep = self.mock(job.time, "sleep")

    def mock(self, owner, name, **options):
        return self.stack.enter_context(patch.object(owner, name, **options))

    def board_done(self, preflight, admission, algorithm, output, **options):
        output.mkdir()
        report = {"status": job.board_study.PASS, "hardware_convergence_measured": True}
        (output / "results.json").write_text(json.dumps(report))
        return report

    def run_job(self, **options):
        return job.run(self.preflight, self.output, self.requests, preflight_unit="offline.service",
                       preflight_invocation=INVOCATION, **options)

    def saved(self):
        return json.loads((self.output / "results.json").read_text())

    def test_all_exact_prerequisites_then_serial_three_algorithm_matrix(self):
        result = self.run_job()
        self.assertEqual(result["status"], job.PASS)
        self.assertEqual(self.board.call_count, 3)
        self.assertEqual([call.args[2] for call in self.board.call_args_list], list(job.preparation.ALGORITHMS))
        self.assertEqual([call.kwargs["device"] for call in self.board.call_args_list], [0, 1, 1])
        self.assertTrue(all(call.kwargs["repeats"] == 3 and call.kwargs["execute"]
                            for call in self.board.call_args_list))
        self.assertTrue(result["hardware_convergence_measured"])
        self.assertFalse(result["spine_comparison"])
        self.assertFalse(result["publication_match"])

    def test_running_offline_or_return_waits_without_requesting_board(self):
        self.states.return_value = state("active")
        with patch.object(job.time, "monotonic", side_effect=[0, 2]), self.assertRaises(TimeoutError):
            self.run_job(maximum_wait=1)
        self.board.assert_not_called()
        self.assertFalse(self.saved()["board_requested"])
        self.output = self.root / "return-timeout"
        self.states.side_effect = lambda unit: state() if unit == "offline.service" else state("active")
        with patch.object(job.time, "monotonic", side_effect=[0, 2]), self.assertRaises(TimeoutError):
            self.run_job(maximum_wait=1)
        self.board.assert_not_called()

    def test_local_returns_keep_exact_algorithm_admission_and_service_gates(self):
        for request in self.requests[1:]:
            path = request.returned / "results.json"
            report = json.loads(path.read_text())
            report["status"] = job.local_follow.PASS
            path.write_text(json.dumps(report))
        result = self.run_job()
        self.assertEqual(result["status"], job.PASS)
        self.assertEqual(self.board.call_count, 3)
        self.board.reset_mock()
        request = self.requests[1]
        path = request.returned / "results.json"
        good = json.loads(path.read_text())
        for changes in ({"algorithm": "full_pagerank"}, {"admission": {}},
                        {"status": "FAILED_RETAINED"}, {"errors": ["timing failed"]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                path.write_text(json.dumps({**good, **changes}))
                job.ready(request)
        path.write_text(json.dumps(good))
        self.states.return_value = state(InvocationID="b" * 32)
        with self.assertRaisesRegex(ValueError, "changed"):
            job.ready(request)
        self.board.assert_not_called()

    def test_failed_or_changed_service_offline_report_or_admission_blocks_board(self):
        self.states.return_value = state("failed")
        with self.assertRaises(ValueError):
            self.run_job()
        self.output = self.root / "changed"
        self.states.return_value = state(InvocationID="b" * 32)
        with self.assertRaises(ValueError):
            self.run_job()
        self.states.return_value = state()
        self.output = self.root / "offline-failed"
        (self.preflight / "results.json").write_text(json.dumps({"status": "FAILED_RETAINED"}))
        with self.assertRaisesRegex(ValueError, "offline full-graph"):
            self.run_job()
        self.board.assert_not_called()
        self.requests[1].admission.write_text("changed admission")
        with self.assertRaisesRegex(ValueError, "exact admitted"):
            job.ready(self.requests[1])
        self.requests[0].admission.write_text(json.dumps({"synthetic": "different bitstream"}))
        with self.assertRaisesRegex(ValueError, "exact admitted"):
            job.ready(self.requests[0])

    def test_failure_in_child_stops_remaining_algorithms_and_retains_child(self):
        def fail(preflight, admission, algorithm, output, **options):
            output.mkdir()
            (output / "results.json").write_text(json.dumps({"status": "FAILED_RETAINED"}))
            raise ValueError("hardware smoke mismatch")

        self.board.side_effect = fail
        with self.assertRaisesRegex(ValueError, "hardware smoke"):
            self.run_job()
        self.assertEqual(self.board.call_count, 1)
        self.assertEqual(self.saved()["matrices"][0]["status"], "FAILED_RETAINED")
        self.assertFalse(self.saved()["hardware_convergence_measured"])

    def test_rejected_prerequisite_can_retain_other_matrices_but_never_pass(self):
        rejected = self.requests[-1]
        self.states.side_effect = lambda unit: state("failed") if unit == rejected.unit else state()
        with self.assertRaisesRegex(ValueError, "independent matrices retained"):
            self.run_job(continue_independent_prerequisites=True)
        report = self.saved()
        self.assertEqual(self.board.call_count, 2)
        self.assertNotIn(rejected.algorithm, [call.args[2] for call in self.board.call_args_list])
        self.assertEqual(report["status"], "FAILED_RETAINED")
        self.assertFalse(report["hardware_convergence_measured"])
        self.assertEqual(report["prerequisite_failures"][0]["algorithm"], rejected.algorithm)
        self.assertFalse(report["prerequisite_failures"][0]["board_requested"])
        self.assertTrue(all(row["status"] == job.board_study.PASS for row in report["matrices"]))

    def test_rejected_first_prerequisite_does_not_starve_later_pending_artifact(self):
        rejected, pending, admitted = self.requests
        polls = {pending.unit: 0}

        def service(unit):
            if unit == rejected.unit:
                return state(InvocationID="b" * 32)
            if unit == pending.unit:
                polls[unit] += 1
                return state("active") if polls[unit] == 1 else state()
            return state()

        self.states.side_effect = service
        with self.assertRaisesRegex(ValueError, "independent matrices retained"):
            self.run_job(continue_independent_prerequisites=True)
        self.assertEqual([call.args[2] for call in self.board.call_args_list],
                         [admitted.algorithm, pending.algorithm])
        self.sleep.assert_called_once()
        self.assertIn("changed", self.saved()["prerequisite_failures"][0]["error"])

    def test_independent_mode_does_not_bypass_offline_or_child_failure(self):
        self.states.return_value = state("failed")
        with self.assertRaises(ValueError):
            self.run_job(continue_independent_prerequisites=True)
        self.board.assert_not_called()
        self.assertEqual(self.saved()["prerequisite_failures"], [])
        self.output = self.root / "child-failure"
        self.states.return_value = state()
        self.board.side_effect = RuntimeError("device failed; do not continue")
        with self.assertRaisesRegex(RuntimeError, "device failed"):
            self.run_job(continue_independent_prerequisites=True)
        self.assertEqual(self.board.call_count, 1)
        self.assertEqual(self.saved()["prerequisite_failures"], [])

    def test_independent_mode_still_requires_all_three_passes(self):
        report = self.run_job(continue_independent_prerequisites=True)
        self.assertEqual(report["status"], job.PASS)
        self.assertEqual(self.board.call_count, 3)
        self.assertEqual(report["prerequisite_failures"], [])

    def test_collected_preflight_requires_explicit_pin_and_complete_evidence_replay(self):
        self.states.side_effect = lambda unit: state(LoadState="not-found", InvocationID="") \
            if unit == "offline.service" else state()
        with self.assertRaisesRegex(ValueError, "disappeared"):
            self.run_job()
        self.board.assert_not_called()
        self.output = self.root / "replay"
        path = self.preflight / "results.json"
        path.write_text(json.dumps({"status": job.analysis.PASS, "pins": []}))
        digest = job.preparation.identity(path)["sha256"]
        with patch.object(job.recheck, "recheck", return_value={"synthetic": "complete replay"}) as replay:
            result = self.run_job(completed_preflight_sha256=digest)
        replay.assert_called_once()
        self.assertEqual(result["status"], job.PASS)
        self.assertIn("NOT_SERVICE_EXIT_ATTESTATION", result["offline_acceptance"])

    def test_completed_preflight_cannot_bypass_pin_replay_or_changed_live_service(self):
        path = self.preflight / "results.json"
        path.write_text(json.dumps({"status": job.analysis.PASS, "pins": []}))
        digest = job.preparation.identity(path)["sha256"]
        with self.assertRaisesRegex(ValueError, "SHA-256 differs"):
            self.run_job(completed_preflight_sha256="a" * 64)
        self.output = self.root / "incomplete"
        with self.assertRaisesRegex(ValueError, "preparation cannot establish"):
            self.run_job(completed_preflight_sha256=digest)
        self.output = self.root / "restarted"
        self.states.return_value = state(InvocationID="b" * 32)
        with patch.object(job.recheck, "recheck", return_value={}), self.assertRaisesRegex(ValueError, "changed"):
            self.run_job(completed_preflight_sha256=digest)
        self.board.assert_not_called()

    def test_invalid_scope_paths_services_or_unbounded_wait_rejected(self):
        item = self.requests[0]
        for changes in ({"algorithm": "full_pagerank"}, {"unit": "bad;unit"}, {"invocation": "missing"},
                        {"device": True}, {"returned": Path("relative")},
                        {"admission": Path("/unrelated/admission.json")}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                job.Request(**{**item.__dict__, **changes})
        for requests in (self.requests[:2], [item, item, item]):
            with self.assertRaises(ValueError):
                job.run(self.preflight, self.output, requests, preflight_unit="offline.service",
                        preflight_invocation=INVOCATION)
        with self.assertRaises(ValueError):
            self.run_job(maximum_wait=0)
        with self.assertRaises(ValueError):
            self.run_job(continue_independent_prerequisites=1)


if __name__ == "__main__":
    unittest.main()
