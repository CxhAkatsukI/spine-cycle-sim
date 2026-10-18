"""Offline continuation fixtures; no FPGA service or card is operated."""

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.paired_board import continuation as job
from test_grasu_continuous_supervisor import INVOCATION, state


class PairedContinuationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.preflight = self.root / "offline"
        self.preflight.mkdir()
        (self.preflight / "results.json").write_text("{}")
        self.source = self.root / "producer"
        self.source.mkdir()
        self.rows = []
        self.producer = {"status": job.producer.PASS, "errors": [], "hardware_convergence_measured": True,
                         "board_requested": True, "preflight": job.preparation.identity(
                             self.preflight / "results.json"), "pins": [], "requests": [], "matrices": [],
                         "production_baseline_admitted": False, "spine_comparison": False, "publication_match": False}
        for algorithm in job.preparation.ALGORITHMS:
            child = self.source / algorithm
            child.mkdir()
            (child / "results.json").write_text("{}")
            spine = self.root / ("spine-" + algorithm)
            spine.mkdir()
            for name in ("results.json", "admission.json"):
                (spine / name).write_text("{}")
            admission = str(self.root / (algorithm + "-admission.json"))
            self.rows.append({"algorithm": algorithm,
                              "gr": {"report": str(child / "results.json"), "admission": admission},
                              "spine": {"report": str(spine / "results.json"),
                                        "admission": str(spine / "admission.json")}})
            self.producer["requests"].append({"algorithm": algorithm, "admission": admission})
            self.producer["matrices"].append({"algorithm": algorithm, "output": str(child),
                "status": job.board_study.PASS, "report": job.preparation.identity(child / "results.json")})
        self.request_path = self.root / "requests.json"
        self.request_path.write_text(json.dumps(self.rows))
        self.write_producer()
        self.output = self.root / "output"
        self.states = self.mock(job, "service_state", return_value=state())
        self.mock(job, "runner_pins", return_value=[])
        self.replay = self.mock(job.study, "run", side_effect=self.replayed)
        self.mock(job.time, "sleep")

    def mock(self, owner, name, **kwargs):
        return self.stack.enter_context(patch.object(owner, name, **kwargs))

    def write_producer(self):
        (self.source / "results.json").write_text(json.dumps(self.producer))

    def replayed(self, preflight, requests, output):
        output.mkdir()
        report = {"status": job.analysis.PASS, "errors": [], "rows": [{}] * 24, "final_figures_admitted": False}
        (output / "results.json").write_text(json.dumps(report))
        return report

    def run_job(self, **options):
        return job.run(self.preflight, self.request_path, self.source, self.output,
                       producer_unit="exact.service", producer_invocation=INVOCATION, **options)

    def saved(self):
        return json.loads((self.output / "results.json").read_text())

    def test_exact_terminal_producer_then_one_existing_offline_replay(self):
        result = self.run_job()
        self.assertEqual(result["status"], job.analysis.PASS)
        self.replay.assert_called_once_with(self.preflight, self.request_path, self.output / "paired_replay")
        self.assertTrue(result["producer_exit_attested"])
        self.assertFalse(result["final_figures_admitted"])
        self.assertFalse(result["board_requested"])
        job.preparation.unchanged(result["pins"], full=True)

    def test_active_result_success_is_not_terminal_and_timeout_retains_failure(self):
        self.states.return_value = state("active")
        with patch.object(job.time, "monotonic", side_effect=[0, 2]), self.assertRaises(TimeoutError):
            self.run_job(maximum_wait=1)
        self.replay.assert_not_called()
        self.assertEqual(self.saved()["status"], "FAILED_RETAINED")
        self.assertFalse(self.saved()["producer_exit_attested"])
        self.assertFalse((self.output / "paired_replay").exists())

    def test_failed_changed_or_collected_producer_rejected(self):
        for index, changed in enumerate((state("failed"), state(InvocationID="b" * 32),
                                          state(LoadState="not-found", InvocationID=""))):
            self.output = self.root / f"failure-{index}"
            self.states.return_value = changed
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.run_job()
        self.replay.assert_not_called()

    def test_incomplete_unbound_or_promoted_producer_rejected(self):
        original = json.loads(json.dumps(self.producer))
        changes = [lambda r: r.update(status="RUNNING_weighted_sssp"),
                   lambda r: r.update(errors=["hardware mismatch"]),
                   lambda r: r.update(publication_match=True),
                   lambda r: r.update(preflight={"path": "/other/results.json"}),
                   lambda r: r["matrices"].pop(),
                   lambda r: r["requests"][1].update(algorithm="weighted_sssp"),
                   lambda r: r["requests"][0].update(admission="/other/artifact.json"),
                   lambda r: r["matrices"][0].update(output="/other/producer"),
                   lambda r: r["matrices"][0]["report"].update(sha256="wrong")]
        for index, change in enumerate(changes):
            self.output = self.root / f"unbound-{index}"
            self.producer = json.loads(json.dumps(original))
            change(self.producer)
            self.write_producer()
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.run_job()
        self.replay.assert_not_called()

    def test_spine_or_runner_pin_drift_while_waiting_prevents_replay(self):
        def drift(unit):
            Path(self.rows[0]["spine"]["report"]).write_text("changed")
            return state("active")

        self.states.side_effect = drift
        with self.assertRaisesRegex(ValueError, "changed"):
            self.run_job()
        self.replay.assert_not_called()

    def test_producer_restart_after_replay_retains_nonadmission(self):
        self.states.side_effect = [state(), state(InvocationID="b" * 32)]
        with self.assertRaisesRegex(ValueError, "changed"):
            self.run_job()
        self.assertFalse(self.saved()["final_figures_admitted"])
        self.assertTrue((self.output / "paired_replay/results.json").exists())

    def test_replay_failure_retained_without_replacement_or_automatic_retry(self):
        self.replay.side_effect = ValueError("raw result differs")
        with self.assertRaisesRegex(ValueError, "raw result"):
            self.run_job()
        self.assertEqual(self.saved()["status"], "FAILED_RETAINED")
        with self.assertRaises(FileExistsError):
            self.run_job()
        self.assertEqual(self.replay.call_count, 1)

    def test_invalid_limits_and_foreign_child_rejected(self):
        for options in ({"maximum_wait": 0}, {"maximum_wait": True}, {"poll_seconds": 301}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_job(**options)
        self.rows[0]["gr"]["report"] = "/foreign/results.json"
        self.request_path.write_text(json.dumps(self.rows))
        with self.assertRaisesRegex(ValueError, "declared producer"):
            self.run_job()
        self.replay.assert_not_called()


class RegisteredPairedRequestTests(unittest.TestCase):
    def test_current_pairing_uses_current_admissions_and_fixed_spine_reports(self):
        root = Path(__file__).resolve().parents[1]
        candidate = root / ("docs/experiments/comparisons/grasu_regraph_stage_validation/"
                            "evaluation_impact/hardware_validation/complete_pipeline/"
                            "production_routing/comparison_candidate")
        current = json.loads((candidate / "fullgraph_requests.json").read_text())
        paired = job.study.requests(candidate / "paired_requests.json")
        campaign = Path("/data/chuxiao/experiments/baseline_hardware_validation_20261015")
        self.assertEqual([row["algorithm"] for row in current], list(job.preparation.ALGORITHMS))
        short_names = ("sssp", "cc", "respr")
        for request, pair, short in zip(current, paired, short_names, strict=True):
            with self.subTest(algorithm=request["algorithm"]):
                self.assertEqual(pair["algorithm"], request["algorithm"])
                self.assertEqual(pair["gr"], {
                    "report": str(campaign / "fullgraph-board-continuation-v10" /
                                  request["algorithm"] / "results.json"),
                    "admission": request["admission"]})
                self.assertEqual(pair["spine"], {
                    "report": str(campaign / f"spine-resident-{short}-board-v2/results.json"),
                    "admission": str(campaign / "spine-resident-freeze-v1/results.json")})


if __name__ == "__main__":
    unittest.main()
