"""Fail closed on incomplete/ambiguous optional HLS and cycle-model probes."""

import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.model_adapter import require_case_report


class AdapterReportTests(unittest.TestCase):
    def test_complete_model_and_hls_reports(self):
        self.assertEqual(require_case_report(
            "Routed shared-master PMA adapter PASS cases=288 "
            "pressure_latency_registration_and_completion_checks=PASS\n", hls=False), 288)
        self.assertEqual(require_case_report("HLS shared-fixture packet check PASS cases=27\n", hls=True), 27)

    def test_missing_or_ambiguous_hls_gate(self):
        good = "HLS shared-fixture packet check PASS cases=27\n"
        for text in ("", "PASS", good * 2, good.replace("27", "26"), "prefix " + good):
            with self.subTest(text=text), self.assertRaises(ValueError):
                require_case_report(text, hls=True)

    def test_model_requires_pressure_gate(self):
        for text in ("Routed shared-master PMA adapter PASS cases=288\n",
                     "Routed shared-master PMA adapter PASS cases=287 "
                     "pressure_latency_registration_and_completion_checks=PASS\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                require_case_report(text, hls=False)


if __name__ == "__main__":
    unittest.main()
