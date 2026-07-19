from __future__ import annotations

import unittest

from scripts.analyze_phase3b_bottlenecks import enrich_predictions


class Phase3BBottleneckTests(unittest.TestCase):
    def test_classifies_trusted_reader_replay_case(self) -> None:
        rows = [
            {
                "case": "reader_replay",
                "sweep": "replay_fallback_boundary",
                "successful_repeats": "3",
                "repeats": "3",
                "median_kernel_e2e_ms": "120.0",
                "median_maint_ms": "10.0",
                "median_conv_span_ms": "100.0",
                "median_reader_ms": "95.0",
                "median_batches": "1",
                "median_target_level": "0",
                "median_active_records": "4097",
                "median_touched_tiles": "16",
                "actual_cycles": "1000",
                "predicted_cycles": "1100",
                "error_pct": "10",
                "abs_error_pct": "10",
            }
        ]

        report = enrich_predictions(rows, 20.0, 25.0)

        self.assertEqual(report[0]["trusted_status"], "trusted")
        self.assertEqual(report[0]["gap_class"], "within_current_dstage_model")
        self.assertEqual(report[0]["bottleneck"], "dstage_reader_replay_dominant")

    def test_classifies_full_tile_gap_even_when_maintenance_dominates(self) -> None:
        rows = [
            {
                "case": "full_gap",
                "sweep": "full_tile_work",
                "successful_repeats": "3",
                "repeats": "3",
                "median_kernel_e2e_ms": "110.0",
                "median_maint_ms": "80.0",
                "median_conv_span_ms": "20.0",
                "median_reader_ms": "10.0",
                "median_batches": "1",
                "median_target_level": "0",
                "median_active_records": "4",
                "median_touched_tiles": "1",
                "median_full_path_tiles": "1",
                "tile_max_work": "8192",
                "actual_cycles": "1000",
                "predicted_cycles": "1400",
                "error_pct": "40",
                "abs_error_pct": "40",
            }
        ]

        report = enrich_predictions(rows, 20.0, 25.0)

        self.assertEqual(report[0]["trusted_status"], "untrusted")
        self.assertEqual(report[0]["gap_class"], "large_full_tile_low_replay_gap")
        self.assertEqual(report[0]["bottleneck"], "maintenance_dominant")

    def test_marks_multibatch_as_diagnostic_out_of_scope(self) -> None:
        rows = [
            {
                "case": "repeat_fanout",
                "sweep": "multibatch_level_probe",
                "successful_repeats": "3",
                "repeats": "3",
                "median_kernel_e2e_ms": "10.0",
                "median_maint_ms": "5.0",
                "median_conv_span_ms": "4.0",
                "median_reader_ms": "3.0",
                "median_batches": "3",
                "median_target_level": "1",
                "median_active_records": "64",
                "median_touched_tiles": "4",
                "actual_cycles": "1000",
                "predicted_cycles": "1010",
                "error_pct": "1",
                "abs_error_pct": "1",
            }
        ]

        report = enrich_predictions(rows, 20.0, 25.0)

        self.assertEqual(report[0]["trusted_status"], "diagnostic_out_of_scope")
        self.assertEqual(report[0]["gap_class"], "multibatch_level_state_diagnostic")


if __name__ == "__main__":
    unittest.main()
