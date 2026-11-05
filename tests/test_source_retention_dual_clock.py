from copy import deepcopy
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import clock_profile, dual_clock_route


PROFILE = [140, 500, 430, 0]


def topology(data=141, hbm=430):
    return {"clock": [(kind, name, value) for (kind, name), value in
                      zip(clock_profile.NAMES, (data, 500, hbm))]}


def notices():
    return ("[AUTO-FREQ-SCALING-04] The kernel clock ulp_ucs/aclk_kernel_00 has an original "
            "frequency equal to 150 MHz. The frequency has been automatically changed to 141.4 MHz\n"
            "[AUTO-FREQ-SCALING-07] The system clock hbm_aclk has an original frequency equal to "
            "450 MHz. The frequency has been automatically changed to 430.8 MHz\n")


def timing():
    return "\n".join([
        "WNS(ns)", "-----", "-0.402 -422.072 2976 2816293 0.009 0 0 2811680 0 0 0 1159817",
        "| Intra Clock Table",
        "clk_kernel_00_unbuffered_net -0.402 -420.762 2942 2003319 0.009 0 0 2003319 2.633 0 0 772066",
        "hbm_aclk -0.099 -1.310 34 378042 0.010 0 0 378042 0.001 0 0 197192",
        "| Inter Clock Table",
    ])


class DualClockTest(unittest.TestCase):
    def test_only_downclocking_and_exact_topology(self):
        payload = {"clock_freq_topology": {"m_count": "3", "m_clock_freq": [
            {"m_type": kind, "m_name": name, "m_freq_Mhz": str(mhz)}
            for kind, name, mhz in topology()["clock"]]}}
        before = deepcopy(payload)
        derived = clock_profile.retarget(payload, PROFILE)
        self.assertEqual(payload, before)
        self.assertEqual([r["m_freq_Mhz"] for r in derived["clock_freq_topology"]["m_clock_freq"]],
                         ["140", "500", "430"])
        with self.assertRaisesRegex(ValueError, "never increase"):
            clock_profile.retarget(payload, [145, 500, 430, 0])

    def test_only_expected_complete_profiles(self):
        for profile in ([141, 500, 430, 0], [140, 499, 430, 0], [140, 500, 455, 0],
                        [True, 500, 430, 0], [140, 500, 430]):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                clock_profile.validate(profile)

    def test_vendor_logs_and_packaged_clocks_must_agree(self):
        self.assertEqual(dual_clock_route.vendor_profile(topology(), notices(), PROFILE),
                         {"data_mhz": "141.4", "hbm_mhz": "430.8"})
        for image, log, profile in ((topology(140), notices(), PROFILE),
                                    (topology(), notices() + notices(), PROFILE),
                                    (topology(), notices(), [145, 500, 430, 0])):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                dual_clock_route.vendor_profile(image, log, profile)

    def test_all_nominal_failures_are_retained_and_covered(self):
        result = dual_clock_route.timing_failure(timing(), PROFILE)
        self.assertFalse(result["nominal_timing_pass"])
        self.assertAlmostEqual(result["domains"]["hbm_aclk"]["period_extension_margin_ns"],
                               -0.099 + 1000 / 430 - 1000 / 450)
        for text, profile in ((timing().replace("0.009 0 0 2811680", "-0.009 -1 1 2811680"), PROFILE),
                              (timing().replace("2976", "2977"), PROFILE),
                              (timing().replace("hbm_aclk", "unexpected_clock"), PROFILE),
                              (timing(), [145, 500, 430, 0])):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                dual_clock_route.timing_failure(text, profile)

    def test_driver_profile_and_board_identity_are_checked(self):
        before = {"bdf": "card", "uuid": "image", "binary": "pin", "driver_reported_mhz": PROFILE}
        for after in ({**before, "bdf": "other"}, {**before, "driver_reported_mhz": [141, 500, 430, 0]}):
            with patch.object(clock_profile.clocks, "replay", side_effect=[before, after]), self.assertRaises(ValueError):
                clock_profile.validate_after({"before": "pin"}, "after", PROFILE)
        with patch.object(clock_profile.clocks, "replay", return_value=before):
            clock_profile.validate_after({"before": "pin"}, "after", PROFILE)

    def test_programming_uses_the_same_finite_memory_budget_as_the_arm(self):
        with patch.object(clock_profile, "execute", return_value="program") as execute, \
                patch.object(clock_profile.clocks, "capture", return_value="clock"), \
                patch.object(clock_profile, "check"):
            result = clock_profile.prepare("binary", "expected", PROFILE,
                "output", "spine", 3, "node", "card", memory_gib=24)
        self.assertEqual(execute.call_args.kwargs, {"memory_gib": 24})
        self.assertEqual(result, {"program": "program", "before": "clock"})


if __name__ == "__main__":
    unittest.main()
