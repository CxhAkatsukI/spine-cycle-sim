from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import derated_route, derated_screen


def topology(hbm, data=150, connections=()):
    return dict(clock=[(*key, hbm if key == derated_route.HBM else data if key == derated_route.DATA else mhz)
                       for key, mhz in derated_route.NOMINAL.items()], connections=connections)


def notice(clock="hbm_aclk", frequency="449.2"):
    return (f"WARNING: [AUTO-FREQ-SCALING-07] The system clock {clock} has an original frequency equal to "
            f"450 MHz. The frequency has been automatically changed to {frequency} MHz to enable proper functionality.")


TIMING = """    WNS(ns) TNS(ns) endpoints total WHS THS endpoints total WPWS TPWS endpoints total
------------------
-0.004 -0.006 2 200 0.006 0 0 200 0.001 0 0 90
| Intra Clock Table
hbm_aclk -0.004 -0.006 2 100 0.006 0 0 100 0.001 0 0 50
| Inter Clock Table
"""


class DeratedScreenTest(unittest.TestCase):
    def test_nominal_and_other_derating_bins_never_launch(self):
        for new, log in ((topology(450), ""), (topology(440), notice(frequency="440.1"))):
            self.assertIsNone(derated_route.compatible_profile(topology(432, 149), new, log, 445))

    def test_exact_hbm_only_derating_passes(self):
        self.assertEqual(derated_route.compatible_profile(topology(432, 149), topology(449), notice(), 445), "449.2")
        self.assertEqual(derated_route.check_timing(TIMING, 445)["nominal_failing_setup_endpoints"], 2)

    def test_other_clock_or_connections_rejected(self):
        for new, log in ((topology(449, 149), notice()), (topology(449, connections=(1,)), notice()),
                         (topology(449), notice("clk_kernel_00")), (topology(449), notice(frequency="448.2")),
                         (topology(449), notice() + "\n" + notice("clk_kernel_00"))):
            with self.subTest(new=new, log=log), self.assertRaises(ValueError):
                derated_route.compatible_profile(topology(450), new, log, 445)

    def test_other_timing_failure_or_insufficient_margin_rejected(self):
        for timing in (TIMING.replace("2 200", "3 200"), TIMING.replace("0.006 0 0 200", "-0.001 -0.001 1 200"),
                       TIMING.replace("-0.004 -0.006", "-0.040 -0.060")):
            with self.subTest(timing=timing), self.assertRaisesRegex(ValueError, "not covered"):
                derated_route.check_timing(timing, 445)

    def test_fixture_rejects_missing_or_mixed_input_files(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(derated_screen, "unchanged"):
                for pins in ([{"path": str(root / "wrong.u32le")}],
                             [{"path": str(root / "tasks.u32le")}, {"path": str(root / "other/initial.u32le")}],
                             [{"path": str(root / "tasks.u32le")}] * 2):
                    with self.subTest(pins=pins), self.assertRaises(ValueError):
                        derated_screen.fixture_directory(pins, ("tasks",))


if __name__ == "__main__":
    unittest.main()
