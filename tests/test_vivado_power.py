from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.evidence.vivado_power import (
    VivadoPowerError,
    parse_vivado_power_log,
    render_power_tcl,
)


REPORT = """
| Total On-Chip Power (W)  | 38.265       |
|   FPGA Power (W)         | 29.490       |
|   HBM Power (W)          | 8.775        |
| Design Power Budget (W)  | 123.000      |
| Dynamic (W)              | 27.677       |
| Device Static (W)        | 10.588       |
| Confidence Level         | Low          |
| Simulation Activity File | ---          |
3.1 By Hierarchy
----------------
+--------------------------------------------------------+-----------+
| Name                                                   | Power (W) |
+--------------------------------------------------------+-----------+
| level0_wrapper                                         |    27.622 |
|       buffer_spine_partconv_compute_kernel_1_value_out |     0.001 |
|       buffer_spine_partconv_rdmaint_kernel_1_edge_out  |     0.002 |
|       hmss_0                                           |    17.674 |
|       spine_partconv_compute_kernel_1                  |     0.205 |
|       spine_partconv_rdmaint_kernel_1                  |     1.891 |
+--------------------------------------------------------+-----------+

339 Infos, 370 Warnings, 1 Critical Warnings and 0 Errors encountered.
report_power completed successfully
"""


class VivadoPowerTests(unittest.TestCase):
    def test_tcl_freezes_vectorless_activity_and_both_reports(self) -> None:
        text = render_power_tcl(
            Path("/tmp/design routed.dcp"),
            Path("/tmp/summary.rpt"),
            Path("/tmp/hierarchy.rpt"),
        )
        self.assertIn("open_checkpoint {/tmp/design routed.dcp}", text)
        self.assertIn("-default_toggle_rate 12.5", text)
        self.assertIn("-default_static_probability 0.5", text)
        self.assertIn("report_power -file {/tmp/summary.rpt}", text)
        self.assertIn("report_power -hierarchical", text)

    def _parse(self, text: str = REPORT) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "impl.log"
            path.write_text(text, encoding="utf-8")
            return parse_vivado_power_log(path)

    def test_parses_summary_and_components(self) -> None:
        result = self._parse()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["summary"]["confidence_level"], "Low")
        self.assertAlmostEqual(result["summary"]["total_on_chip_w"], 38.265)
        components = {
            row["component"]: row["power_w"]
            for row in result["publication_components"]
        }
        self.assertEqual(components["hbm_subsystem"], 17.674)
        self.assertEqual(components["reader_maintenance_kernel"], 1.891)

    def test_rejects_incomplete_report(self) -> None:
        with self.assertRaisesRegex(VivadoPowerError, "did not complete"):
            self._parse(REPORT.replace("report_power completed successfully", ""))

    def test_rejects_nonconserving_summary(self) -> None:
        broken = REPORT.replace("|   HBM Power (W)          | 8.775", "|   HBM Power (W)          | 9.775")
        with self.assertRaisesRegex(VivadoPowerError, "does not conserve"):
            self._parse(broken)

    def test_rejects_missing_kernel_component(self) -> None:
        broken = REPORT.replace("|       spine_partconv_compute_kernel_1                  |     0.205 |\n", "")
        with self.assertRaisesRegex(VivadoPowerError, "missing hierarchy component"):
            self._parse(broken)


if __name__ == "__main__":
    unittest.main()
