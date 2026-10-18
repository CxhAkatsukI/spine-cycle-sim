"""Checkpoint diagnostics are not bitstream generation or board admission."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.postroute import (
    analysis, inputs, probe,
)
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity


def report(path, values="0.001 0.000 0 900 0.001 0.000 0 900 0.000 0.000 0 100", admitted=True):
    path.write_text("WNS(ns) TNS(ns) TNS Failing Endpoints Total Endpoints WHS(ns)\n"
                    "-------\n" + values + "\n" +
                    ("All user specified timing constraints are met.\n" if admitted else ""))


class ProductionPostrouteTests(unittest.TestCase):
    def test_summary_preserves_all_failure_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timing.rpt"
            report(path, "-0.107 -18.575 443 900 0.001 0.000 0 900 0.000 0.000 0 100", False)
            row = analysis.timing(path)
            self.assertEqual(row["metrics"]["setup"]["failing"], 443)
            self.assertEqual(row["metrics"]["setup"]["total_ns"], -18.575)
            self.assertFalse(row["summary_constraints_pass"])
            self.assertEqual(row["report"], identity(path))

    def test_only_complete_strict_summary_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timing.rpt"
            for admitted in (True, False):
                report(path, admitted=admitted)
                self.assertEqual(analysis.timing(path)["summary_constraints_pass"], admitted)
            for index in (0, 4, 8):
                values = "0.001 0.000 0 900 0.001 0.000 0 900 0.000 0.000 0 100".split()
                values[index:index + 3] = ["-0.001", "-0.001", "1"]
                report(path, " ".join(values))
                self.assertFalse(analysis.timing(path)["summary_constraints_pass"])

    def test_bad_numeric_fields_are_rejected(self):
        for bad in ("nan", "inf", "-inf", "word"):
            for index in (0, 1, 4, 5, 8, 9):
                with self.subTest(bad=bad, index=index), tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "timing.rpt"
                    values = "0.001 0.000 0 900 0.001 0.000 0 900 0.000 0.000 0 100".split()
                    values[index] = bad
                    report(path, " ".join(values))
                    with self.assertRaises(ValueError):
                        analysis.timing(path)

    def test_bad_counts_total_or_duplicate_summary_are_rejected(self):
        for values in ("0 0 901 900 0 0 0 900 0 0 0 100", "0 0 -1 900 0 0 0 900 0 0 0 100",
                       "0 1 0 900 0 0 0 900 0 0 0 100", "0 0 0 900"):
            with self.subTest(values=values), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "timing.rpt"
                report(path, values)
                with self.assertRaises(ValueError): analysis.timing(path)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timing.rpt"
            report(path)
            path.write_text(path.read_text() * 2)
            with self.assertRaises(ValueError): analysis.timing(path)

    def test_all_passes_retained_even_when_final_pass_regresses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in analysis.PASSES:
                report(root / (name + ".rpt"))
            report(root / "replication.rpt", "-0.1 -1 10 900 0 0 0 900 0 0 0 100", False)
            for name in ("refined.dcp", "clocks.rpt", "final_route_status.rpt", "final_drc.rpt"):
                (root / name).write_text("fixture")
            result = analysis.inspect(root)
            self.assertTrue(result["any_summary_constraints_pass"])
            self.assertFalse(result["final_summary_constraints_pass"])
            self.assertEqual([row["pass"] for row in result["passes"]], list(analysis.PASSES))
            (root / "fanout.rpt").unlink()
            with self.assertRaises(FileNotFoundError): analysis.inspect(root)

    def test_invalid_or_live_parent_never_reads_checkpoint(self):
        with patch.object(inputs, "service_state", return_value={}), \
                patch.object(inputs, "route_finished", return_value=False), \
                patch.object(inputs.artifacts, "completed") as artifacts:
            for unit, invocation in (("bad;unit", "0" * 32), ("unit.service", "bad"),
                                     ("unit.service", "0" * 32)):
                with self.assertRaises(ValueError): inputs.admit(Path("unused"), unit, invocation)
            artifacts.assert_not_called()

    def test_bad_parent_stops_before_environment_or_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(inputs, "admit", side_effect=ValueError("bad parent")), \
                    patch.object(probe.environment, "capture") as environment, \
                    patch.object(probe, "run_link") as tool, self.assertRaises(ValueError):
                probe.run(root, "unit.service", "0" * 32, root / "new", root, root, root, root)
            environment.assert_not_called()
            tool.assert_not_called()
            saved = json.loads((root / "new/results.json").read_text())
            self.assertEqual(saved["status"], "FAILED_RETAINED")
            self.assertFalse(saved["board_admitted"])
            self.assertFalse(saved["bitstream_generated"])

    def test_parent_requires_unique_checkpoint_and_unchanged_identities(self):
        for damage in (None, "binary", "source", "duplicate_checkpoint", "duplicate_report"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in ("manifest.json", "execution.json", "candidate.hw.xclbin", "source.cpp",
                             "link/impl_1/level0_wrapper_routed.dcp",
                             "reports/impl_1_hw_bb_locked_timing_summary_routed.rpt"):
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("fixture")
                execution = {"manifest": identity(root / "manifest.json"),
                             "xclbin": identity(root / "candidate.hw.xclbin")}
                manifest = {"algorithm": "residual_pagerank", "pins": [identity(root / "source.cpp")]}
                if damage in ("binary", "source"):
                    (root / ("candidate.hw.xclbin" if damage == "binary" else "source.cpp")).write_text("changed")
                if damage in ("duplicate_checkpoint", "duplicate_report"):
                    duplicate = root / ("link/extra/impl_1/level0_wrapper_routed.dcp" if damage == "duplicate_checkpoint"
                                        else "reports/extra/impl_1_hw_bb_locked_timing_summary_routed.rpt")
                    duplicate.parent.mkdir(parents=True, exist_ok=True)
                    duplicate.write_text("duplicate")
                with patch.object(inputs, "service_state", return_value={}), \
                        patch.object(inputs, "route_finished", return_value=True), \
                        patch.object(inputs.artifacts, "completed", return_value=(execution, manifest)):
                    if damage is None:
                        result = inputs.admit(root, "unit.service", "0" * 32)
                        self.assertEqual(result["algorithm"], "residual_pagerank")
                        self.assertEqual(len(result["pins"]), 6)
                    else:
                        with self.assertRaises(ValueError): inputs.admit(root, "unit.service", "0" * 32)

    def test_tcl_has_exact_clocks_predeclared_passes_and_no_bitstream(self):
        if not shutil.which("tclsh"):
            self.skipTest("tclsh unavailable")
        source = Path(probe.__file__).with_name("refine.tcl")
        for period in ("6.667", "6.5"):
            script = f"""
set argv {{input.dcp output}}
set calls {{}}
proc set_param {{args}} {{}}
proc open_checkpoint {{args}} {{}}
proc get_clocks {{args}} {{return [lindex $args end]}}
proc get_property {{name clock}} {{
    if {{$clock eq {{clk_kernel_00_unbuffered_net}}}} {{return {period}}}
    if {{$clock eq {{clk_kernel_01_unbuffered_net}}}} {{return 2.000}}
    if {{$clock eq {{hbm_aclk}}}} {{return 2.222}}
    error unknown_clock
}}
foreach command {{report_clocks report_timing_summary report_route_status report_drc write_checkpoint}} {{
    proc $command {{args}} {{}}
}}
proc phys_opt_design {{args}} {{lappend ::calls $args}}
if {{[catch {{source {{{source}}}}} message]}} {{puts stderr $message; exit 1}}
puts $calls
"""
            result = subprocess.run(["tclsh"], input=script, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0 if period == "6.667" else 1, result.stderr)
            if period == "6.667":
                self.assertIn("-clock_opt {-directive AggressiveFanoutOpt} {-directive AlternateReplication}",
                              result.stdout)
        self.assertNotIn("write_bitstream", source.read_text())
        self.assertNotIn("create_clock", source.read_text())


if __name__ == "__main__":
    unittest.main()
