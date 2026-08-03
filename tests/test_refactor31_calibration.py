from __future__ import annotations

import unittest

from spine_cycle_sim.calibration.refactor31 import (
    parse_refactor31_fpga_log,
    summarize_refactor31_fpga_runs,
)


def result_line(
    *, launch: int, reference_validated: int = 0, compute_ms: float = 2.0
) -> str:
    return (
        "SEGMENTED_FALLBACK_HW PASS case=active_gate launch="
        f"{launch} phase=valid-{launch} malformed_index=-1 "
        f"reference_validated={reference_validated} vertices=1024 edges=17 "
        "active_sources=17 active_records=17 next_active=16 processed=17 "
        "path=2 fallback=1 task_error=0 ack_eligible=0 reader_ms=1.5 "
        f"compute_ms={compute_ms} conv_ms={compute_ms} wall_ms=2.25 errors=0"
    )


class Refactor31CalibrationTests(unittest.TestCase):
    def test_parser_converts_milliseconds_at_the_routed_clock(self) -> None:
        record = parse_refactor31_fpga_log(result_line(launch=1))[0]
        self.assertEqual(record.compute_cycles, 320_000)
        self.assertTrue(record.timing_admitted)
        self.assertFalse(record.correctness_admitted)

    def test_reference_validated_launch_is_correctness_admitted(self) -> None:
        record = parse_refactor31_fpga_log(
            result_line(launch=1, reference_validated=1)
        )[0]
        self.assertTrue(record.correctness_admitted)

    def test_summary_does_not_upgrade_unvalidated_repeats(self) -> None:
        records = parse_refactor31_fpga_log(
            "\n".join(
                result_line(launch=launch, compute_ms=2.0 + launch / 100.0)
                for launch in range(1, 6)
            )
        )
        summary = summarize_refactor31_fpga_runs(records)[0]
        self.assertEqual(summary["repeat_gate"], 1)
        self.assertEqual(summary["correctness_gate"], 0)
        self.assertEqual(summary["calibration_admitted"], 0)
        self.assertEqual(summary["timing_baseline_scope"], "timing_stability_only")

    def test_summary_admits_five_correctness_gated_repeats(self) -> None:
        records = parse_refactor31_fpga_log(
            "\n".join(
                result_line(launch=launch, reference_validated=1)
                for launch in range(1, 6)
            )
        )
        summary = summarize_refactor31_fpga_runs(records)[0]
        self.assertEqual(summary["calibration_admitted"], 1)

    def test_parser_rejects_missing_structured_results(self) -> None:
        with self.assertRaisesRegex(ValueError, "no SEGMENTED_FALLBACK_HW"):
            parse_refactor31_fpga_log("ordinary host output")

    def test_parser_rejects_negative_timing(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid timing compute_ms"):
            parse_refactor31_fpga_log(result_line(launch=1, compute_ms=-1.0))


if __name__ == "__main__":
    unittest.main()
