from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/collect_candidate10_maintenance_control_rtl_oracle.py"
SPEC = importlib.util.spec_from_file_location(
    "candidate10_maintenance_control", SCRIPT
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Candidate10MaintenanceControlOracleTest(unittest.TestCase):
    def test_parse_summary_preserves_burst_and_beat_ledgers(self) -> None:
        parsed = MODULE.parse_summary(
            "MAINT_CONTROL_RTL case=zero cycles=4490 "
            "meta_ar=370 meta_requested_r=373 meta_r=373 "
            "meta_aw=49 meta_requested_w=162 meta_w=162 meta_b=49 "
            "result_aw=67 result_requested_w=88 result_w=88 result_b=67 "
            "sorter_aw=0 sorter_w=0 sorter_ar=0\n"
        )
        self.assertEqual(parsed["cycles"], 4490)
        self.assertEqual(parsed["meta_ar"], 370)
        self.assertEqual(parsed["meta_requested_r"], parsed["meta_r"])
        self.assertEqual(parsed["meta_requested_w"], parsed["meta_w"])
        self.assertEqual(parsed["result_requested_w"], parsed["result_w"])

    def test_parse_rejects_timeout(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            MODULE.parse_summary("MAINT_CONTROL_RTL_TIMEOUT cycles=200000")

    def test_instance_parser_covers_plain_and_parameterized_children(self) -> None:
        text = """
          spine_partconv_rdmaint_kernel_plain child0 (.ap_clk(ap_clk));
          spine_partconv_rdmaint_kernel_param #(.WIDTH(8)) child1 (
            .ap_clk(ap_clk));
        """
        self.assertEqual(
            set(MODULE.INSTANCE_RE.findall(text)),
            {
                "spine_partconv_rdmaint_kernel_plain",
                "spine_partconv_rdmaint_kernel_param",
            },
        )

    def test_repository_evidence_passes_when_present(self) -> None:
        evidence = (
            ROOT
            / "docs/evidence/candidate10_maintenance_control_rtl_20260726.json"
        )
        if not evidence.exists():
            self.skipTest("maintenance-control RTL evidence has not been collected")
        report = json.loads(evidence.read_text(encoding="utf-8"))
        zero = report["zero_edge"]
        rtl = zero["rtl_ideal_child_responder"]
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(rtl["cycles"], 4490)
        self.assertEqual(zero["sst_execution_driven_cycles"], 4490)
        self.assertEqual(zero["sst_control_floor_cycles"], 4490)
        self.assertGreater(zero["sst_control_floor_padding_cycles"], 0)
        self.assertEqual(zero["sst_control_floor_memory_overrun_cycles"], 0)
        self.assertEqual(rtl["meta_requested_r"], rtl["meta_r"])
        self.assertEqual(rtl["meta_requested_w"], rtl["meta_w"])
        self.assertEqual(rtl["meta_aw"], rtl["meta_b"])
        self.assertEqual(rtl["result_requested_w"], rtl["result_w"])
        self.assertEqual(rtl["result_aw"], rtl["result_b"])
        self.assertGreater(zero["hardware_minus_rtl_cycles"], 30_000)


if __name__ == "__main__":
    unittest.main()
