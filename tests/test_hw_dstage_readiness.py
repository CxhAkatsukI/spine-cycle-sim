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

    def test_phase3a2_tile_matrices_are_disjoint_and_instrumented(self) -> None:
        calibration = matrix_by_name("phase3a2_tile_calibration")
        holdout = matrix_by_name("phase3a2_tile_holdout")
        regression = matrix_by_name("phase3a2_tile_regression")

        calibration_cases = {case.case for case in calibration}
        holdout_cases = {case.case for case in holdout}
        self.assertEqual(len(calibration), 12)
        self.assertEqual(len(holdout), 8)
        self.assertTrue(calibration_cases.isdisjoint(holdout_cases))
        self.assertEqual(len(regression), 1)
        for case in [*calibration, *holdout, *regression]:
            self.assertIn("--print-tile-schedule", case.args)

    def test_phase3a3_tile_matrices_cover_multi_partition_holdout(self) -> None:
        calibration = matrix_by_name("phase3a3_tile_calibration")
        holdout = matrix_by_name("phase3a3_tile_holdout")

        calibration_cases = {case.case for case in calibration}
        holdout_cases = {case.case for case in holdout}
        self.assertEqual(len(calibration), 12)
        self.assertEqual(len(holdout), 8)
        self.assertTrue(calibration_cases.isdisjoint(holdout_cases))
        self.assertTrue(
            any("--partition-tile-work" in case.args for case in calibration)
        )
        self.assertTrue(any("--partition-tile-work" in case.args for case in holdout))
        self.assertIn("a3_calib_mt_4095_4096_4097_4098", calibration_cases)
        self.assertIn("a3_hold_mp_p0_4095_p1_4096_p2_4097_p3_4098", holdout_cases)
        for case in [*calibration, *holdout]:
            self.assertIn("--print-tile-schedule", case.args)


if __name__ == "__main__":
    unittest.main()
