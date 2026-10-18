"""Compile-to-link orchestration invariants; no FPGA tool or device access."""

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_grasu_continuous_supervisor import INVOCATION, state
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build import compile_follow as job


class CompileFollowTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.source = self.root / "sources"
        self.source.mkdir()
        (self.source / "sources.json").write_text("frozen source index")
        (self.source / "top.cpp").write_text("frozen source")
        self.compilation = self.root / "compile"
        self.compilation.mkdir()
        self.manifest = {"source_manifest": job.identity(self.source / "sources.json"),
                         "integration_revision": "b" * 40, "algorithm": "full_pagerank",
                         "clock_mhz": 150, "pins": [], **job.inputs.CLAIMS}
        self.manifest_file = self.compilation / "manifest.json"
        self.write_manifest()
        self.execution = {"status": "COMPILATION_PASS_AWAITING_RESOURCE_RTL_AND_ROUTE",
                          "errors": [], "algorithm": "full_pagerank",
                          "manifest": job.identity(self.manifest_file)}
        self.write_execution()
        self.output = self.root / "follow"
        self.mock(job, "current", return_value=Path("/synthetic-cgroup"))
        self.mock(job, "verify", return_value={"bounded": True})
        self.mock(job.inputs, "verify", return_value={"integration_revision": "b" * 40,
                                                      "files": [{"member": "top.cpp"}]})
        self.mock(job, "runner_pins", return_value=[])
        self.states = self.mock(job, "service_state", return_value=state())
        self.sleep = self.mock(job.time, "sleep")
        self.route = self.mock(job.route_study, "run", side_effect=self.link)

    def mock(self, owner, name, **options):
        return self.stack.enter_context(patch.object(owner, name, **options))

    def write_manifest(self):
        self.manifest_file.write_text(json.dumps(self.manifest))

    def write_execution(self):
        (self.compilation / "execution.json").write_text(json.dumps(self.execution))

    def link(self, compilation, storage, output, *paths, **options):
        output.mkdir()
        (output / "candidate.hw.xclbin").write_text("synthetic binary")
        report = {"status": job.LINK_PASS, "errors": [], "algorithm": "full_pagerank",
                  "integration_revision": "b" * 40, "rtl_admitted": False,
                  "board_admitted": False, "publication_match": False,
                  "xclbin": job.identity(output / "candidate.hw.xclbin")}
        (output / "execution.json").write_text(json.dumps(report))
        return report

    def run_job(self, **options):
        arguments = {"compile_unit": "compile.service", "compile_invocation": INVOCATION,
                     "algorithm": "full_pagerank", **options}
        return job.run(self.compilation, self.source, self.root / "storage", self.output,
                       self.root / "xilinx", self.root / "platform", self.root / "compat",
                       self.root / "shim", **arguments)

    def saved(self):
        return json.loads((self.output / "results.json").read_text())

    def test_exact_compile_then_existing_route_owner_without_admission_claims(self):
        self.states.side_effect = [state("active"), state(), state()]
        result = self.run_job(timing_profile=job.PROFILE)
        self.assertEqual(result["status"], job.PASS)
        self.assertTrue(result["link_completed"])
        self.assertEqual(len(result["compile_states"]), 2)
        self.sleep.assert_called_once()
        self.route.assert_called_once()
        self.assertEqual(self.route.call_args.kwargs, {"timing_profile": job.PROFILE})
        self.assertEqual(result["route_execution"], job.identity(self.output / "route/execution.json"))
        for key in (*job.inputs.CLAIMS, "rtl_admitted", "timing_admitted"):
            self.assertIs(result[key], False)

    def test_missing_changed_failed_or_timed_out_compile_never_starts_link(self):
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
        self.route.assert_not_called()

    def test_source_algorithm_clock_or_manifest_claim_mismatch_stops_early(self):
        original = self.manifest.copy()
        for index, change in enumerate(({"source_manifest": {}}, {"integration_revision": "c" * 40},
                {"algorithm": "residual_pagerank"}, {"clock_mhz": 200}, {"board_admitted": True})):
            self.output = self.root / str(index)
            self.manifest = {**original, **change}
            self.write_manifest()
            with self.assertRaisesRegex(ValueError, "requested sources"):
                self.run_job()
        self.states.assert_not_called()
        self.route.assert_not_called()

    def test_source_or_manifest_mutation_during_wait_is_retained(self):
        for index, path in enumerate((self.source / "top.cpp", self.manifest_file)):
            self.output = self.root / str(index)
            self.states.return_value = state("active")
            before = path.read_text()
            self.sleep.side_effect = lambda _, path=path: path.write_text("changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                self.run_job()
            path.write_text(before)
        self.route.assert_not_called()

    def test_service_success_without_complete_compile_report_is_rejected(self):
        original = self.execution.copy()
        for index, change in enumerate(({"status": "COMPILING_NOT_ROUTED"}, {"errors": ["failed"]},
                                       {"algorithm": "connected_components"}, {"manifest": {}})):
            self.output = self.root / str(index)
            self.execution = {**original, **change}
            self.write_execution()
            with self.assertRaisesRegex(ValueError, "successful compilation"):
                self.run_job()
        self.route.assert_not_called()

    def test_child_failure_preserves_its_execution_record(self):
        def fail(*args, **options):
            output = args[2]
            output.mkdir()
            (output / "execution.json").write_text('{"status":"FAILED_RETAINED","errors":["resource conflict"]}')
            raise ValueError("resource conflict")

        self.route.side_effect = fail
        with self.assertRaisesRegex(ValueError, "resource conflict"):
            self.run_job()
        result = self.saved()
        self.assertEqual(result["status"], "FAILED_RETAINED")
        self.assertEqual(result["route_execution"], job.identity(self.output / "route/execution.json"))
        self.assertFalse(result["link_completed"])

    def test_changed_binary_child_scope_or_compile_identity_prevents_success(self):
        cases = ({"status": "ROUTING_EXPERIMENT_NOT_RTL_OR_BOARD_ADMISSION"}, {"errors": ["failure"]},
                 {"algorithm": "connected_components"}, {"integration_revision": "c" * 40},
                 {"board_admitted": True}, {"xclbin": {}})
        for index, change in enumerate(cases):
            self.output = self.root / str(index)
            def altered(*args, change=change, **options):
                result = {**self.link(*args, **options), **change}
                (args[2] / "execution.json").write_text(json.dumps(result))
                return result
            self.route.side_effect = altered
            with self.assertRaises(ValueError):
                self.run_job()
            self.assertFalse(self.saved()["link_completed"])
        self.output = self.root / "changed-service"
        self.route.side_effect = self.link
        self.states.side_effect = [state(), state(InvocationID="c" * 32)]
        with self.assertRaisesRegex(ValueError, "invocation changed"):
            self.run_job()

    def test_unbounded_follower_rejected_before_sources_or_vendor_tools(self):
        self.mock(job, "verify", side_effect=ValueError("unbounded"))
        with self.assertRaisesRegex(ValueError, "unbounded"):
            self.run_job()
        self.states.assert_not_called()
        self.route.assert_not_called()
        self.assertEqual(self.saved()["status"], "FAILED_RETAINED")

    def test_invalid_options_or_existing_output_cannot_start_link(self):
        for options in ({"compile_unit": "bad;unit"}, {"compile_invocation": "unknown"},
                        {"maximum_wait": True}, {"maximum_wait": 0}, {"maximum_wait": 133201},
                        {"poll_seconds": 0}, {"poll_seconds": 301}, {"timing_profile": "unknown"},
                        {"algorithm": "sssp"}):
            with self.assertRaises(ValueError):
                self.run_job(**options)
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            self.run_job()
        self.route.assert_not_called()


if __name__ == "__main__":
    unittest.main()
