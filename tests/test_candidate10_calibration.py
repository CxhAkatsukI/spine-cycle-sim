from __future__ import annotations

import unittest

from spine_cycle_sim.calibration.candidate10 import (
    Candidate10TimingRecord,
    candidate10_prediction_rows,
    fit_candidate10_residual,
    summarize_candidate10_predictions,
)


def record(
    case: str,
    role: str,
    edges: int,
    blocks: int,
    simulated: float,
    hardware: float,
    unique_sources: int | None = None,
) -> Candidate10TimingRecord:
    return Candidate10TimingRecord(
        case,
        case,
        role,
        edges,
        blocks,
        max(0, edges) if unique_sources is None else unique_sources,
        simulated,
        hardware,
    )


class Candidate10CalibrationTests(unittest.TestCase):
    def test_fit_uses_residual_over_execution_driven_cycles(self) -> None:
        rows = [
            record("zero", "calibration", 0, 0, 1_000, 11_000),
            record("one", "calibration", 1, 1, 1_100, 11_115),
            record("sources", "calibration", 128, 1, 2_000, 13_285),
            record("blocks", "calibration", 256, 2, 3_000, 15_570),
            record(
                "extra",
                "calibration",
                128,
                1,
                2_000,
                12_805,
                unique_sources=32,
            ),
        ]
        model = fit_candidate10_residual(rows)
        predictions = candidate10_prediction_rows(rows, model)
        self.assertAlmostEqual(model.fixed_cycles, 10_000.0)
        self.assertAlmostEqual(model.per_classify_block_cycles, 5.0)
        self.assertAlmostEqual(model.per_unique_source_cycles, 10.0)
        self.assertAlmostEqual(model.per_extra_edge_cycles, 5.0)
        self.assertLess(max(row["abs_error_pct"] for row in predictions), 1e-9)

    def test_holdout_is_not_required_to_fit(self) -> None:
        calibration = [
            record("zero", "calibration", 0, 0, 100, 200),
            record("one", "calibration", 1, 1, 100, 303),
            record("two", "calibration", 2, 1, 100, 305),
            record("four", "calibration", 4, 2, 100, 510),
            record("extra", "calibration", 8, 1, 100, 320, unique_sources=2),
        ]
        base = fit_candidate10_residual(calibration)
        with_holdout = fit_candidate10_residual(
            calibration + [record("bad", "holdout", 99, 1, 1, 1_000_000)]
        )
        self.assertEqual(base, with_holdout)

    def test_negative_mechanism_coefficient_is_clamped(self) -> None:
        rows = [
            record("zero", "calibration", 0, 0, 1_000, 11_000),
            record("one", "calibration", 1, 1, 1_000, 11_100),
            record("block", "calibration", 128, 1, 1_000, 31_000),
            record("many", "calibration", 4_096, 32, 1_000, 701_000),
            record(
                "extra",
                "calibration",
                128,
                1,
                1_000,
                11_200,
                unique_sources=32,
            ),
        ]
        model = fit_candidate10_residual(rows)
        self.assertGreaterEqual(model.per_classify_block_cycles, 0.0)
        self.assertGreaterEqual(model.per_unique_source_cycles, 0.0)
        self.assertGreaterEqual(model.per_extra_edge_cycles, 0.0)

    def test_out_of_domain_residual_is_bounded_and_labeled(self) -> None:
        calibration = [
            record("zero", "calibration", 0, 0, 100, 200),
            record("one", "calibration", 1, 1, 100, 303),
            record("two", "calibration", 2, 1, 100, 305),
            record("four", "calibration", 4, 2, 100, 510),
            record("extra", "calibration", 8, 1, 100, 320, unique_sources=2),
        ]
        model = fit_candidate10_residual(calibration)
        out_of_domain = record(
            "large-extra", "holdout", 1_000, 8, 500, 5_000, unique_sources=1
        )
        row = candidate10_prediction_rows([out_of_domain], model)[0]
        self.assertFalse(row["within_calibration_domain"])
        self.assertLess(
            row["residual_correction_cycles"],
            row["raw_extrapolated_residual_cycles"],
        )
        self.assertEqual(
            model.max_calibration_extra_edges,
            max(item.input_edges - item.unique_sources for item in calibration),
        )

    def test_fit_requires_zero_five_rows_and_extra_edge_anchor(self) -> None:
        with self.assertRaises(ValueError):
            fit_candidate10_residual(
                [
                    record(str(index), "calibration", index + 1, 1, 1, 2)
                    for index in range(5)
                ]
            )
        with self.assertRaises(ValueError):
            fit_candidate10_residual(
                [record("zero", "calibration", 0, 0, 1, 2)]
            )
        with self.assertRaises(ValueError):
            fit_candidate10_residual(
                [
                    record("zero", "calibration", 0, 0, 1, 2),
                    record("one", "calibration", 1, 1, 1, 2),
                    record("two", "calibration", 2, 1, 1, 2),
                    record("three", "calibration", 3, 1, 1, 2),
                    record("four", "calibration", 4, 1, 1, 2),
                ]
            )

    def test_summary_separates_roles(self) -> None:
        rows = [
            {"role": "calibration", "abs_error_pct": 1.0},
            {"role": "calibration", "abs_error_pct": 3.0},
            {"role": "holdout", "abs_error_pct": 7.0},
        ]
        summary = summarize_candidate10_predictions(rows)
        self.assertEqual(summary[0]["median_abs_error_pct"], 2.0)
        self.assertEqual(summary[1]["max_abs_error_pct"], 7.0)


if __name__ == "__main__":
    unittest.main()
