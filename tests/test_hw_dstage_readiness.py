from __future__ import annotations

import unittest

from scripts.run_hw_dstage_readiness import matrix_by_name


class DStageReadinessMatrixTests(unittest.TestCase):
    def test_phase3a1_final_holdout_is_unseen(self) -> None:
        calibration_cases = {case.case for case in matrix_by_name("phase3a1_calibration")}
        holdout_cases = {case.case for case in matrix_by_name("phase3a1_holdout")}
        final_cases = {case.case for case in matrix_by_name("phase3a1_final_holdout")}

        self.assertEqual(len(final_cases), 8)
        self.assertTrue(final_cases.isdisjoint(calibration_cases))
        self.assertTrue(final_cases.isdisjoint(holdout_cases))
        self.assertIn("final_fanout_e3072_s48", final_cases)
        self.assertIn("final_repeat_fanout_e768_b2_s96", final_cases)


if __name__ == "__main__":
    unittest.main()
