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

    def test_phase3a4_replay_matrices_are_controlled_and_disjoint(self) -> None:
        calibration = matrix_by_name("phase3a4_replay_calibration")
        holdout = matrix_by_name("phase3a4_replay_holdout")

        calibration_cases = {case.case for case in calibration}
        holdout_cases = {case.case for case in holdout}
        self.assertEqual(len(calibration), 31)
        self.assertEqual(len(holdout), 10)
        self.assertTrue(calibration_cases.isdisjoint(holdout_cases))
        self.assertTrue(
            any("--multi-source-tile-work" in case.args for case in calibration)
        )
        self.assertTrue(
            any("--striped-source-tile-work" in case.args for case in calibration)
        )
        self.assertTrue(
            any("--striped-source-tile-work" in case.args for case in holdout)
        )
        self.assertIn("a4_calib_src_s128_w1", calibration_cases)
        self.assertIn("a4_hold_replay_above_s8193_t16", holdout_cases)
        for case in [*calibration, *holdout]:
            self.assertIn("--print-tile-schedule", case.args)

    def test_phase3b_bottleneck_matrices_are_broad_and_separated(self) -> None:
        synthetic = matrix_by_name("phase3b_bottleneck_synthetic")
        multibatch = matrix_by_name("phase3b_multibatch_probe")
        phase3a4 = {
            case.case
            for case in [
                *matrix_by_name("phase3a4_replay_calibration"),
                *matrix_by_name("phase3a4_replay_holdout"),
            ]
        }

        synthetic_cases = {case.case for case in synthetic}
        multibatch_cases = {case.case for case in multibatch}
        self.assertEqual(len(synthetic), 22)
        self.assertEqual(len(multibatch), 4)
        self.assertTrue(synthetic_cases.isdisjoint(multibatch_cases))
        self.assertTrue(synthetic_cases.isdisjoint(phase3a4))
        self.assertIn("p3b_replay_above_s8193_t8", synthetic_cases)
        self.assertIn("p3b_multipart_s96_mixed", synthetic_cases)
        self.assertIn("p3b_repeat_fanout_e1024_b3_s64", multibatch_cases)
        for case in [*synthetic, *multibatch]:
            self.assertIn("--print-tile-schedule", case.args)
        for case in synthetic:
            self.assertTrue(
                any(
                    option in case.args
                    for option in (
                        "--multi-source-tile-work",
                        "--striped-source-tile-work",
                        "--partition-tile-work",
                    )
                )
            )

    def test_phase3c_matrices_are_holdout_or_final_validation(self) -> None:
        calibration = matrix_by_name("phase3c_full_partition_calibration")
        holdout = matrix_by_name("phase3c_full_partition_holdout")
        final = matrix_by_name("phase3c_final_validation")
        phase3b_cases = {case.case for case in matrix_by_name("phase3b_bottleneck_synthetic")}

        calibration_cases = {case.case for case in calibration}
        holdout_cases = {case.case for case in holdout}
        final_cases = {case.case for case in final}
        self.assertEqual(len(calibration), 23)
        self.assertEqual(len(holdout), 12)
        self.assertEqual(len(final), 8)
        self.assertTrue(calibration_cases.isdisjoint(holdout_cases))
        self.assertTrue(calibration_cases.isdisjoint(final_cases))
        self.assertTrue(holdout_cases.isdisjoint(final_cases))
        self.assertTrue(calibration_cases.isdisjoint(phase3b_cases))
        self.assertTrue(holdout_cases.isdisjoint(phase3b_cases))
        self.assertIn("p3c_final_full_large_s32_w1024", final_cases)
        self.assertIn("p3c_final_replay_above_s4098_t16", final_cases)
        for case in [*calibration, *holdout, *final]:
            self.assertIn("--print-tile-schedule", case.args)
        self.assertTrue(any(case.sweep == "full_low_replay" for case in calibration))
        self.assertTrue(
            any(case.sweep == "multi_partition_interaction" for case in calibration)
        )
        self.assertTrue(any(case.sweep == "small_multitile_fixed" for case in holdout))


if __name__ == "__main__":
    unittest.main()
