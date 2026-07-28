from __future__ import annotations

from pathlib import Path
import unittest

from spine_cycle_sim.evidence.vivado_power import render_power_tcl


class VivadoPowerTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
