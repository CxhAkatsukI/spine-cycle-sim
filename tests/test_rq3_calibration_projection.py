from __future__ import annotations

import unittest

from spine_cycle_sim.calibration.rq3 import project_rq3_stage_ledger


class RQ3CalibrationProjectionTests(unittest.TestCase):
    def test_projection_preserves_group_fractions_and_closes(self) -> None:
        row = {
            "total_cycles": 100,
            "ten_stage_supported": True,
            "ten_stage_ledger_closed": True,
            "t_xfer_cycles": 10,
            "t_reduce_cycles": 10,
            "t_carry_cycles": 0,
            "t_directory_cycles": 0,
            "t_seed_cycles": 0,
            "t_switch_cycles": 0,
            "t_resolve_cycles": 20,
            "t_app_cycles": 40,
            "t_drain_cycles": 20,
            "t_sync_cycles": 0,
        }

        projected = project_rq3_stage_ledger(
            row,
            predicted_maintenance_cycles=30,
            predicted_iterative_span_cycles=160,
        )

        self.assertEqual(projected["calibrated_t_xfer_cycles"], 15)
        self.assertEqual(projected["calibrated_t_reduce_cycles"], 15)
        self.assertEqual(projected["calibrated_t_resolve_cycles"], 40)
        self.assertEqual(projected["calibrated_t_app_cycles"], 80)
        self.assertEqual(projected["calibrated_t_drain_cycles"], 40)
        self.assertEqual(projected["calibrated_total_cycles"], 190)
        self.assertTrue(projected["calibrated_ledger_closed"])
        self.assertFalse(projected["fpga_per_stage_counters_available"])

    def test_zero_iterative_group_is_supported_for_zero_round_case(self) -> None:
        row = {
            "total_cycles": 20,
            "ten_stage_supported": True,
            "ten_stage_ledger_closed": True,
            "t_xfer_cycles": 5,
            "t_reduce_cycles": 5,
            "t_carry_cycles": 0,
            "t_directory_cycles": 0,
            "t_seed_cycles": 5,
            "t_switch_cycles": 5,
            "t_resolve_cycles": 0,
            "t_app_cycles": 0,
            "t_drain_cycles": 0,
            "t_sync_cycles": 0,
        }

        projected = project_rq3_stage_ledger(
            row,
            predicted_maintenance_cycles=40,
            predicted_iterative_span_cycles=0,
        )

        self.assertEqual(projected["calibrated_total_cycles"], 40)
        self.assertEqual(projected["calibrated_t_resolve_cycles"], 0)

    def test_nonzero_target_without_raw_attribution_fails_closed(self) -> None:
        row = {
            "total_cycles": 20,
            "ten_stage_supported": True,
            "ten_stage_ledger_closed": True,
            "t_xfer_cycles": 20,
        }

        with self.assertRaisesRegex(ValueError, "no raw stage attribution"):
            project_rq3_stage_ledger(
                row,
                predicted_maintenance_cycles=20,
                predicted_iterative_span_cycles=1,
            )

    def test_open_ledger_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "closed ten-stage ledger"):
            project_rq3_stage_ledger(
                {
                    "total_cycles": 1,
                    "ten_stage_supported": True,
                    "ten_stage_ledger_closed": False,
                    "t_xfer_cycles": 1,
                },
                predicted_maintenance_cycles=1,
                predicted_iterative_span_cycles=0,
            )


if __name__ == "__main__":
    unittest.main()
