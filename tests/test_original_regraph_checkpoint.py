import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact, checkpoint, checkpoint_run


class CheckpointContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prebuilt, self.audit, self.output = [self.root / name for name in ("prebuilt", "audit", "output")]
        for path in (self.prebuilt / checkpoint.IMPL, self.prebuilt / "xclbin_hw_pr",
                     self.audit, self.output / "query"):
            path.mkdir(parents=True)
        self.binary = self.prebuilt / "xclbin_hw_pr/graph_fpga.hw..xclbin"
        self.binary.write_bytes(b"binary")
        (self.prebuilt / checkpoint.IMPL / checkpoint.FILES[1]).write_bytes(b"partial")
        (self.output / "embedded.bit").write_bytes(b"partial")
        self.recorded = self.prebuilt / checkpoint.IMPL / "_new_clk_freq"
        self.recorded.write_text("kernel:0:ulp_ucs/aclk_kernel_00:215.1\nsystem::hbm_aclk:450.0\n")
        self.document = {"status": checkpoint.study.STATUS, "errors": [],
                         "pins": [artifact.identity(self.binary)],
                         "artifact": {"data_clock_mhz_from_xclbin": 215}}
        self.save()
        (self.output / "query/design.tsv").write_text("tool_version\tdesign\tpart\n2024.1\tdesign_1\txcu55c-fsvh2892-2L-e\n")
        self.clocks = self.output / "query/clocks.tsv"
        self.clocks.write_text("name\tperiod_ns\twaveform\tgenerated\nkernel\t4.348\t0 2.174\t1\n")
        for name in ("timing.rpt", "route_status.rpt"):
            (self.output / "query" / name).write_text("native report")

    def save(self):
        (self.audit / "results.json").write_text(json.dumps(self.document))

    def analyze(self):
        return checkpoint.analyze(self.output, self.prebuilt, self.audit)

    def test_native_timing_and_exact_bitstream_do_not_promote_other_claims(self):
        with patch.object(checkpoint, "parse_routed_timing", return_value={"wns_ns": 0.1}):
            result = self.analyze()
        self.assertTrue(result["embedded_partial_bitstream_matches_saved_file"])
        self.assertTrue(result["checkpoint_native_timing"]["checkpoint_native_constraints_passed"])
        self.assertAlmostEqual(result["checkpoint_clocks"][0]["frequency_mhz"], 230, places=1)
        self.assertEqual(result["recorded_scaled_clocks_mhz"]["kernel:0:ulp_ucs/aclk_kernel_00"], 215.1)
        for claim in checkpoint.CLAIMS:
            self.assertIs(result[claim], False)
        self.assertFalse(result["constraints_modified"])

    def test_negative_native_timing_is_retained_not_scaled_failure(self):
        with patch.object(checkpoint, "parse_routed_timing", side_effect=ValueError("negative slack")):
            result = self.analyze()
        self.assertFalse(result["checkpoint_native_timing"]["checkpoint_native_constraints_passed"])
        self.assertFalse(result["timing_at_scaled_clock_verified"])

    def test_changed_binary_bitstream_or_failed_audit_rejected(self):
        with patch.object(checkpoint, "parse_routed_timing", return_value={}):
            for field, value in (("status", "FAILED_RETAINED"), ("errors", ["failure"]), ("pins", [])):
                before = copy.deepcopy(self.document)
                self.document[field] = value
                self.save()
                with self.subTest(field=field), self.assertRaises(ValueError):
                    self.analyze()
                self.document = before
            self.save()
            (self.output / "embedded.bit").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "exactly match"):
                self.analyze()

    def test_clock_tables_reject_missing_duplicate_and_nonfinite_values(self):
        original = self.clocks.read_text()
        for replacement in ("name\tperiod_ns\n", original.splitlines()[0] + "\n",
                            original + original.splitlines()[1] + "\n", original.replace("4.348", "nan"),
                            original.replace("4.348", "0"), original.replace("4.348\t0 2.174", "4.348")):
            self.clocks.write_text(replacement)
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                self.analyze()

    def test_recorded_scaled_clock_schema_and_frequency(self):
        original = self.recorded.read_text()
        for replacement in ("system::hbm_aclk:450\n", original + original.splitlines()[0] + "\n",
                            original.replace("215.1", "inf"), original.replace("215.1", "-1")):
            self.recorded.write_text(replacement)
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                checkpoint.clock_requests(self.recorded)

    def test_query_tcl_has_no_reimplementation_or_constraint_mutation(self):
        script = Path(checkpoint.__file__).with_suffix(".tcl").read_text()
        self.assertIn("open_checkpoint $checkpoint", script)
        self.assertIn("report_route_status", script)
        for command in ("create_clock", "set_property", "write_checkpoint", "write_bitstream", "route_design"):
            self.assertNotIn(command, script)


class ProbeRunnerTests(unittest.TestCase):
    def test_environment_uses_private_scratch_and_rejects_license_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "environment.json"
            values = {"XILINX_VIVADO": str(checkpoint_run.VIVADO.parents[1]), "TMPDIR": "/other/live/scratch"}
            captured = {"effective": {"license_value_sha256": {}, "values": values}}
            path.write_text(json.dumps(captured))
            result = checkpoint_run.environment(path, root)
            self.assertEqual(result["TMPDIR"], str(root / "tmp"))
            self.assertEqual(values["TMPDIR"], "/other/live/scratch")
            for key in ("license_value_sha256", "values"):
                bad = copy.deepcopy(captured)
                if key == "values":
                    bad["effective"][key]["XILINXD_LICENSE_FILE"] = "hidden"
                else:
                    bad["effective"][key] = {"hidden": "digest"}
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    checkpoint_run.environment(path, root)

    def test_insufficient_parallel_budget_stops_before_any_tool_and_releases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "memory.events").write_text("oom 0\noom_kill 0\n")
            lease = MagicMock()
            lease.sample.return_value = {"admitted": False}
            with patch.object(checkpoint_run, "current", return_value=root), \
                    patch.object(checkpoint_run, "verify", return_value={}), \
                    patch.object(checkpoint_run, "Lease", return_value=lease), \
                    patch.object(checkpoint_run, "other_builds", return_value=["123 vivado"]), \
                    patch.object(checkpoint_run, "available_memory_bytes", return_value=100), \
                    patch.object(checkpoint_run, "run_link") as execute, \
                    patch.object(checkpoint_run, "run_bounded") as extract:
                with self.assertRaisesRegex(RuntimeError, "no tool launched"):
                    checkpoint_run.run(root, root, root, root / "attempt")
            execute.assert_not_called()
            extract.assert_not_called()
            lease.release.assert_called_once()
            self.assertEqual(lease.sample.call_args.args[1], ["123 vivado"])
            self.assertTrue(lease.sample.call_args.args[2]["allow_bounded_builds"])
            result = json.loads((root / "attempt/results.json").read_text())
            self.assertEqual(result["status"], "FAILED_RETAINED")
            self.assertEqual(len(result["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
