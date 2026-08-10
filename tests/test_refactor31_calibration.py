from __future__ import annotations

import importlib.util
import os
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
import json
from unittest.mock import patch

from spine_cycle_sim.calibration.refactor31 import (
    REFACTOR31_ACTIVE_GATE,
    REFACTOR31_VERTICES,
    fit_refactor31_residual_model,
    load_refactor31_resident_sim_summary,
    parse_refactor31_fpga_log,
    parse_refactor31_real_slice_fpga_log,
    refactor31_fixture_edges,
    summarize_refactor31_fpga_runs,
    summarize_refactor31_real_slice_fpga_runs,
    refactor31_spearman,
    write_refactor31_fixture,
)


MATRIX_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_refactor31_real_slice_matrix.py"
MATRIX_SPEC = importlib.util.spec_from_file_location("refactor31_matrix", MATRIX_SCRIPT)
assert MATRIX_SPEC is not None and MATRIX_SPEC.loader is not None
MATRIX_MODULE = importlib.util.module_from_spec(MATRIX_SPEC)
MATRIX_SPEC.loader.exec_module(MATRIX_MODULE)


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
    def test_matrix_sim_environment_enables_atomic_progress(self) -> None:
        row = {"dataset": "AU", "target_edges": 4_000_000}
        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"SPINE_CAMPAIGN_PROGRESS_INTERVAL_CYCLES": "12345"},
        ):
            environment = MATRIX_MODULE.sim_environment(Path(directory), row)
        expected = (
            Path(directory)
            / "sim"
            / "AU_e4000000"
            / "progress.json"
        ).resolve()
        self.assertEqual(
            environment["SPINE_CAMPAIGN_PROGRESS_PATH"], str(expected)
        )
        self.assertEqual(
            environment["SPINE_CAMPAIGN_PROGRESS_INTERVAL_CYCLES"], "12345"
        )

    def test_real_slice_repeat_summary_gates_and_aggregates(self) -> None:
        line = (
            "REFACTOR31_REAL_SLICE_HW PASS slice=/tmp/au_e100.slice source=9 "
            "vertices=100 graph_edges=100 resident_level=8 rounds=3 "
            "processed_edges=25 reader_cycles={reader} compute_cycles={compute} "
            "paired_cycles={compute} dijkstra_mismatches=0 "
            "reference_validated=1 errors=0"
        )
        records = [
            parse_refactor31_real_slice_fpga_log(
                line.format(reader=100 + index, compute=200 + index)
            )
            for index in range(5)
        ]
        summary = summarize_refactor31_real_slice_fpga_runs(records)
        self.assertEqual(summary["calibration_admitted"], 1)
        self.assertEqual(summary["median_paired_cycles"], 202)

    def test_resident_summary_reconstructs_event_windows(self) -> None:
        payload = {
            "resident_static_sssp": True,
            "resident_static_level": 8,
            "rounds": 2,
            "reader_start_cycles_per_round": [10, 40],
            "reader_end_cycles_per_round": [30, 60],
            "compute_end_cycles_per_round": [35, 58],
            "processed_edges_per_round": [4, 5],
            "correctness_mismatches": 0,
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "maintenance_memory_ledger_closed": True,
            "maintenance_stage_ledger_closed": True,
            "memory_locality_ledger_match": True,
            "backend_arbitration": {"ledger_closed": True},
            "architecture_profile_sha256": "profile-hash",
            "sst_plugin_sha256": "plugin-hash",
            "workload_sha256": "workload-hash",
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            row = load_refactor31_resident_sim_summary(path)
        self.assertEqual(row["raw_reader_cycles"], 40)
        self.assertEqual(row["raw_compute_cycles"], 43)
        self.assertEqual(row["raw_paired_cycles"], 45)
        self.assertEqual(row["processed_edges"], 9)
        self.assertEqual(row["ledger_admitted"], 1)
        self.assertEqual(row["architecture_profile_sha256"], "profile-hash")
        self.assertEqual(row["sst_plugin_sha256"], "plugin-hash")

    def test_nonnegative_residual_fit_recovers_known_shell_cost(self) -> None:
        rows = [
            {
                "rounds": rounds,
                "raw": 1000 + rounds * 10,
                "actual": 1500 + rounds * 110,
            }
            for rounds in (1, 2, 4, 8)
        ]
        model = fit_refactor31_residual_model(
            rows, actual_field="actual", raw_field="raw"
        )
        self.assertAlmostEqual(model.fixed_cycles, 500.0)
        self.assertAlmostEqual(model.per_round_cycles, 100.0)
        self.assertEqual(model.predict(1050, 5), 2050)

    def test_realized_work_residual_recovers_processed_edge_cost(self) -> None:
        rows = [
            {
                "rounds": rounds,
                "processed_edges": edges,
                "raw": 10_000 + edges * 7,
                "actual": 10_400 + rounds * 80 + edges * 12,
            }
            for rounds, edges in ((1, 10), (2, 100), (5, 1_000), (9, 8_000))
        ]
        model = fit_refactor31_residual_model(
            rows,
            actual_field="actual",
            raw_field="raw",
            include_processed_edges=True,
        )
        self.assertAlmostEqual(model.fixed_cycles, 400.0, places=5)
        self.assertAlmostEqual(model.per_round_cycles, 80.0, places=5)
        self.assertAlmostEqual(model.per_processed_edge_cycles, 5.0, places=5)
        self.assertAlmostEqual(model.predict(17_000, 3, 1_000), 22_640.0, places=5)

    def test_realized_work_residual_remains_nonnegative(self) -> None:
        rows = [
            {"rounds": 1, "processed_edges": 1, "raw": 100, "actual": 90},
            {"rounds": 2, "processed_edges": 10, "raw": 200, "actual": 180},
            {"rounds": 3, "processed_edges": 100, "raw": 300, "actual": 250},
        ]
        model = fit_refactor31_residual_model(
            rows,
            actual_field="actual",
            raw_field="raw",
            include_processed_edges=True,
        )
        self.assertEqual(model.fixed_cycles, 0.0)
        self.assertEqual(model.per_round_cycles, 0.0)
        self.assertEqual(model.per_processed_edge_cycles, 0.0)

    def test_relative_weighting_does_not_let_large_rows_dominate(self) -> None:
        rows = [
            {
                "rounds": 1,
                "processed_edges": 0,
                "raw": 100,
                "actual": 200,
            },
            {
                "rounds": 1,
                "processed_edges": 0,
                "raw": 1_000_000,
                "actual": 2_000_000,
            },
        ]
        unweighted = fit_refactor31_residual_model(
            rows,
            actual_field="actual",
            raw_field="raw",
        )
        weighted = fit_refactor31_residual_model(
            rows,
            actual_field="actual",
            raw_field="raw",
            relative_error_weighted=True,
        )
        unweighted_small_error = abs(unweighted.predict(100, 1) - 200) / 200
        weighted_small_error = abs(weighted.predict(100, 1) - 200) / 200
        self.assertLess(weighted_small_error, 0.1)
        self.assertLess(weighted_small_error, unweighted_small_error)

    def test_spearman_handles_ties(self) -> None:
        self.assertAlmostEqual(refactor31_spearman([1, 2, 2, 4], [10, 20, 20, 40]), 1.0)

    def test_real_slice_aggregate_is_correctness_admitted(self) -> None:
        record = parse_refactor31_real_slice_fpga_log(
            "REFACTOR31_REAL_SLICE_HW PASS slice=/tmp/real.slice source=9 "
            "vertices=19399 graph_edges=50000 resident_level=8 rounds=3 "
            "processed_edges=22 "
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
            "graph_edges=1 resident_level=8 rounds=1 processed_edges=1 "
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
