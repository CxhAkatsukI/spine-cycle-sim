"""Local links use strict existing sealing/admission, without FPGA access."""

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_grasu_continuous_supervisor import INVOCATION, state
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build import local_follow as job


class LocalFollowTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.sources = self.root / "sources"
        self.sources.mkdir()
        (self.sources / "sources.json").write_text("frozen index")
        (self.sources / "top.cpp").write_text("frozen source")
        self.compilation = self.root / "compile"
        self.compilation.mkdir()
        self.manifest = {"source_manifest": job.identity(self.sources / "sources.json"),
                         "integration_revision": "b" * 40, "algorithm": "connected_components",
                         "clock_mhz": 150, **job.inputs.CLAIMS}
        self.manifest_path = self.compilation / "manifest.json"
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.output = self.root / "follow"
        self.mock(job, "current", return_value=Path("/test-cgroup"))
        self.mock(job, "verify", return_value={"bounded": True})
        self.mock(job.inputs, "verify", return_value={"integration_revision": "b" * 40,
                                                      "files": [{"member": "top.cpp"}]})
        self.mock(job, "runner_pins", return_value=[])
        self.states = self.mock(job, "service_state", return_value=state())
        self.sleep = self.mock(job.time, "sleep")
        self.seal = self.mock(job.artifacts, "seal", return_value={"sha256": "d" * 64})
        self.receipt = {"algorithm": "connected_components", "integration_revision": "b" * 40,
                        "unit": "link.service", "invocation": INVOCATION}
        self.receipts = self.mock(job.artifacts, "verify", return_value=self.receipt)
        self.admit = self.mock(job.admission, "review", side_effect=self.accept)

    def mock(self, owner, name, **options):
        return self.stack.enter_context(patch.object(owner, name, **options))

    def accept(self, returned, sources, output, **options):
        output.mkdir()
        result = {"status": "ALGORITHM_ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD",
                  "algorithm": "connected_components"}
        (output / "summary.json").write_text(json.dumps(result))
        return result

    def run_job(self, **options):
        arguments = {"unit": "link.service", "invocation": INVOCATION,
                     "algorithm": "connected_components", **options}
        return job.run(self.compilation, self.root / "route", self.sources, self.output, **arguments)

    def saved(self):
        return json.loads((self.output / "results.json").read_text())

    def test_exact_link_then_existing_sealer_and_strict_admission(self):
        self.states.side_effect = [state("active"), state(), state()]
        result = self.run_job()
        self.assertEqual(result["status"], job.PASS)
        self.sleep.assert_called_once()
        self.seal.assert_called_once_with(self.compilation, self.root / "route", self.output / "returned",
                                          unit="link.service", invocation=INVOCATION)
        self.admit.assert_called_once_with(self.output / "returned", self.sources, self.output / "admission",
                                           receipt_sha256="d" * 64)
        self.assertEqual(result["admission"], job.identity(self.output / "admission/summary.json"))
        for key in ("board_requested", *job.artifacts.FLAGS):
            self.assertIs(result[key], False)

    def test_missing_changed_failed_or_incomplete_service_never_seals(self):
        for index, bad in enumerate((state("failed"), state(InvocationID="c" * 32),
                                    state(LoadState="not-found"), state(ExecMainStatus="1"))):
            self.output = self.root / str(index)
            self.states.return_value = bad
            with self.assertRaises(ValueError):
                self.run_job()
            self.assertEqual(self.saved()["status"], "FAILED_RETAINED")
        self.output = self.root / "timeout"
        self.states.return_value = state("active")
        with patch.object(job.time, "monotonic", side_effect=[0, 2]), self.assertRaises(TimeoutError):
            self.run_job(maximum_wait=1)
        self.seal.assert_not_called()
        self.admit.assert_not_called()

    def test_source_algorithm_clock_or_claim_mismatch_never_waits(self):
        for index, change in enumerate(({"source_manifest": {}}, {"algorithm": "full_pagerank"},
                {"integration_revision": "c" * 40}, {"clock_mhz": 200}, {"board_admitted": True})):
            self.output = self.root / str(index)
            self.manifest_path.write_text(json.dumps({**self.manifest, **change}))
            with self.assertRaisesRegex(ValueError, "differs from compilation"):
                self.run_job()
        self.states.assert_not_called()
        self.seal.assert_not_called()

    def test_input_mutation_during_wait_never_seals(self):
        self.states.return_value = state("active")
        self.sleep.side_effect = lambda _: (self.sources / "top.cpp").write_text("changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.run_job()
        self.seal.assert_not_called()

    def test_receipt_scope_mismatch_prevents_admission(self):
        for index, change in enumerate(({"algorithm": "full_pagerank"}, {"integration_revision": "c" * 40},
                                       {"unit": "other.service"}, {"invocation": "c" * 32})):
            self.output = self.root / str(index)
            self.receipts.return_value = {**self.receipt, **change}
            with self.assertRaisesRegex(ValueError, "sealed local"):
                self.run_job()
        self.admit.assert_not_called()

    def test_timing_failure_keeps_receipt_and_failure_without_pass(self):
        self.admit.side_effect = ValueError("setup/hold/pulse timing failed")
        with self.assertRaisesRegex(ValueError, "timing failed"):
            self.run_job()
        result = self.saved()
        self.assertEqual(result["status"], "FAILED_RETAINED")
        self.assertEqual(result["receipt_sha256"], "d" * 64)
        self.assertNotIn("admission", result)
        self.assertFalse(result["board_requested"])

    def test_scope_or_service_changes_after_admission_cannot_pass(self):
        self.admit.side_effect = None
        for index, result in enumerate(({"status": "partial", "algorithm": "connected_components"},
                {"status": "ALGORITHM_ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD", "algorithm": "full_pagerank"})):
            self.output = self.root / str(index)
            self.admit.return_value = result
            with self.assertRaisesRegex(ValueError, "admission incomplete"):
                self.run_job()
        self.output = self.root / "changed-service"
        self.admit.side_effect = self.accept
        self.states.side_effect = [state(), state(InvocationID="c" * 32)]
        with self.assertRaisesRegex(ValueError, "invocation changed"):
            self.run_job()

    def test_containment_and_bad_options_fail_before_sealing(self):
        for options in ({"unit": "bad;unit"}, {"invocation": "unknown"}, {"maximum_wait": True},
                        {"maximum_wait": 0}, {"maximum_wait": 270001}, {"poll_seconds": 0},
                        {"poll_seconds": 301}, {"algorithm": "sssp"}):
            with self.assertRaises(ValueError):
                self.run_job(**options)
        self.mock(job, "verify", side_effect=ValueError("unbounded"))
        with self.assertRaisesRegex(ValueError, "unbounded"):
            self.run_job()
        self.seal.assert_not_called()
        self.admit.assert_not_called()

    def test_existing_output_cannot_be_overwritten(self):
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            self.run_job()
        self.seal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
