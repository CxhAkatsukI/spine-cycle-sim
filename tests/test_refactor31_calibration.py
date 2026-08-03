from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from spine_cycle_sim.calibration.refactor31 import (
    REFACTOR31_ACTIVE_GATE,
    REFACTOR31_VERTICES,
    parse_refactor31_fpga_log,
    parse_refactor31_real_slice_fpga_log,
    refactor31_fixture_edges,
    summarize_refactor31_fpga_runs,
    write_refactor31_fixture,
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
    def test_real_slice_aggregate_is_correctness_admitted(self) -> None:
        record = parse_refactor31_real_slice_fpga_log(
            "REFACTOR31_REAL_SLICE_HW PASS slice=/tmp/real.slice source=9 "
            "vertices=19399 graph_edges=50000 rounds=3 processed_edges=22 "
            "reader_cycles=181597 compute_cycles=220162 "
            "paired_cycles=220162 dijkstra_mismatches=0 "
            "reference_validated=1 errors=0"
        )
        self.assertTrue(record.correctness_admitted)
        self.assertEqual(record.paired_cycles, 220_162)
        self.assertEqual(record.processed_edges, 22)

    def test_real_slice_aggregate_rejects_duplicate_summary(self) -> None:
        line = (
            "REFACTOR31_REAL_SLICE_HW PASS slice=x source=0 vertices=2 "
            "graph_edges=1 rounds=1 processed_edges=1 reader_cycles=1 "
            "compute_cycles=1 paired_cycles=1 dijkstra_mismatches=0 "
            "reference_validated=1 errors=0"
        )
        with self.assertRaisesRegex(ValueError, "expected one"):
            parse_refactor31_real_slice_fpga_log(f"{line}\n{line}\n")

    def test_fixture_generator_matches_hardware_boundaries(self) -> None:
        exact = refactor31_fixture_edges("active_exact_one_tile")
        fallback = refactor31_fixture_edges("active_gate_many_tiles")
        self.assertEqual(len(exact), REFACTOR31_ACTIVE_GATE)
        self.assertEqual(len(fallback), REFACTOR31_ACTIVE_GATE + 1)
        self.assertEqual(exact[0], (65_536, 0, 1, 1))
        self.assertEqual(fallback[-1][0], REFACTOR31_VERTICES - 1)
        self.assertEqual(
            {destination // 65_536 for _, destination, _, _ in fallback},
            set(range(16)),
        )

    def test_fixture_writer_emits_sorted_loadable_slice(self) -> None:
        with TemporaryDirectory() as directory:
            path = write_refactor31_fixture(
                Path(directory) / "probe.slice", "active_exact_many_tiles"
            )
            lines = path.read_text(encoding="ascii").splitlines()
        self.assertIn(f"# vertices={REFACTOR31_VERTICES}", lines)
        records = [
            tuple(map(int, line.split())) for line in lines if not line.startswith("#")
        ]
        self.assertEqual(records, sorted(records, key=lambda edge: edge[:2]))

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
