from __future__ import annotations

import unittest
from pathlib import Path

from spine_cycle_sim.calibration import (
    E2E_PREDICTION_FIELD_ORDER,
    E2EInputs,
    bottleneck,
    build_e2e_prediction,
    component_summary_row,
    compute_overhead_model,
    e2e_group_summary,
    e2e_prediction_field_order,
    fit_reader_model,
    reader_model_to_dict,
)

ROOT = Path(__file__).resolve().parents[1]
FREQ = 134.0


def _ms(cycles: float) -> float:
    return cycles / (FREQ * 1000.0)


def _inputs(**overrides):
    base = dict(
        group="g",
        role="holdout",
        case="c",
        sweep="s",
        batch_edges=4096.0,
        jitter_pct=0.1,
        B_actual=1_000_000.0,
        R_actual=5_000_000.0,
        D_span_actual=6_000_000.0,
        kernel_e2e_actual=7_000_000.0,
        B_pred=1_000_000.0,
        R_pred=5_000_000.0,
        D_span_pred=6_000_000.0,
        overhead_model=0.0,
        b_whatif_speedups={
            "halve_repeated_filter_scans": 1.05,
            "halve_level_write_path": 1.5,
        },
        d_whatif_cycles={},
    )
    base.update(overrides)
    return E2EInputs(**base)


class ReaderModelTests(unittest.TestCase):
    def test_recovers_linear_edge_relationship(self) -> None:
        # reader_cycles = 1500 * traversed_edges (exactly).
        rows = []
        for edges in [512, 4096, 20000, 40960, 81920]:
            cycles = 1500.0 * edges
            rows.append(
                {
                    "median_reader_ms": _ms(cycles),
                    "median_traversed_edges": edges,
                    "tile_full_swept_words": 0.0,
                    "tile_scattered_words": 0.0,
                    "tile_fast_gathered_words": 0.0,
                    "median_active_records": edges / 10.0,
                }
            )
        model = fit_reader_model(rows, freq_mhz=FREQ)
        for row in rows:
            pred = model.predict(row)
            actual = float(row["median_reader_ms"]) * FREQ * 1000.0
            self.assertLess(abs(pred - actual) / actual, 0.02)

    def test_predict_is_non_negative(self) -> None:
        rows = [
            {"median_reader_ms": _ms(1500.0 * e), "median_traversed_edges": e,
             "tile_full_swept_words": 0.0, "tile_scattered_words": 0.0,
             "tile_fast_gathered_words": 0.0, "median_active_records": e}
            for e in [1000, 5000, 25000]
        ]
        model = fit_reader_model(rows, freq_mhz=FREQ)
        empty = {feature: 0.0 for feature in model.features}
        self.assertGreaterEqual(model.predict(empty), 0.0)

    def test_model_to_dict_roundtrips_features(self) -> None:
        rows = [
            {"median_reader_ms": _ms(1500.0 * e), "median_traversed_edges": e,
             "tile_full_swept_words": e, "tile_scattered_words": 0.0,
             "tile_fast_gathered_words": 0.0, "median_active_records": e}
            for e in [1000, 5000, 25000]
        ]
        model = fit_reader_model(rows, freq_mhz=FREQ)
        payload = reader_model_to_dict(model)
        self.assertEqual(payload["target"], "median_reader_ms")
        self.assertEqual(set(payload["standardized_coefficients"]), set(model.features))


class OverheadModelTests(unittest.TestCase):
    def test_median_residual(self) -> None:
        rows = []
        for oh_cycles in [0.0, 134_000.0, -134_000.0]:  # 0, +1ms, -1ms
            rows.append(
                {
                    "median_maint_ms": 1.0,
                    "median_conv_span_ms": 2.0,
                    "median_kernel_e2e_ms": 3.0 + _ms(oh_cycles),
                }
            )
        overhead = compute_overhead_model(rows, freq_mhz=FREQ)
        self.assertAlmostEqual(overhead, 0.0, places=3)

    def test_ignores_rows_missing_fields(self) -> None:
        rows = [{"median_maint_ms": 1.0}]  # no conv_span / kernel_e2e
        self.assertEqual(compute_overhead_model(rows, freq_mhz=FREQ), 0.0)


class BottleneckTests(unittest.TestCase):
    def test_maintenance_dominant(self) -> None:
        self.assertEqual(bottleneck(200, 10, 100, 90), "maintenance_dominant")

    def test_reader_dominant(self) -> None:
        self.assertEqual(bottleneck(10, 95, 100, 5), "reader_dominant")

    def test_compute_tail_dominant(self) -> None:
        self.assertEqual(bottleneck(10, 40, 100, 60), "compute_tail_dominant")

    def test_balanced(self) -> None:
        self.assertEqual(bottleneck(10, 70, 100, 30), "balanced")


class LedgerTests(unittest.TestCase):
    def test_serial_and_no_overhead_and_ideal(self) -> None:
        out = build_e2e_prediction(
            _inputs(B_pred=1_000_000.0, D_span_pred=6_000_000.0, overhead_model=100.0)
        )
        self.assertEqual(out["no_overhead_pred_cycles"], 7_000_000.0)
        self.assertEqual(out["serial_pred_cycles"], 7_000_100.0)
        self.assertEqual(out["ideal_bd_overlap_pred_cycles"], 6_000_100.0)

    def test_d_tail_is_span_minus_reader_clamped(self) -> None:
        out = build_e2e_prediction(
            _inputs(D_span_actual=6_000_000.0, R_actual=5_000_000.0,
                    D_span_pred=6_000_000.0, R_pred=6_500_000.0)
        )
        self.assertEqual(out["D_tail_actual_cycles"], 1_000_000.0)
        self.assertEqual(out["D_tail_pred_cycles"], 0.0)  # clamped, R_pred > D_span_pred

    def test_negative_overhead_is_flagged(self) -> None:
        out = build_e2e_prediction(
            _inputs(B_actual=1_000_000.0, D_span_actual=6_000_000.0,
                    kernel_e2e_actual=6_900_000.0)
        )
        self.assertLess(out["overhead_actual_cycles"], 0.0)
        self.assertEqual(out["overhead_note"], "overlap_or_measurement_window")

    def test_positive_overhead_has_no_note(self) -> None:
        out = build_e2e_prediction(
            _inputs(B_actual=1_000_000.0, D_span_actual=6_000_000.0,
                    kernel_e2e_actual=7_100_000.0)
        )
        self.assertGreater(out["overhead_actual_cycles"], 0.0)
        self.assertEqual(out["overhead_note"], "")

    def test_serial_error_pct(self) -> None:
        out = build_e2e_prediction(
            _inputs(B_pred=1_100_000.0, D_span_pred=6_000_000.0, overhead_model=0.0,
                    kernel_e2e_actual=7_000_000.0)
        )
        # serial_pred = 7_100_000 -> +100_000 / 7_000_000 = ~1.4286%
        self.assertAlmostEqual(out["serial_error_pct"], 100_000 / 7_000_000 * 100.0, places=6)

    def test_whatif_speedups_at_least_one(self) -> None:
        out = build_e2e_prediction(_inputs())
        for key in (
            "whatif_halve_b_repeated_scans_speedup",
            "whatif_halve_b_level_write_path_speedup",
            "whatif_halve_reader_time_speedup",
            "whatif_ideal_bd_overlap_speedup",
        ):
            self.assertGreaterEqual(out[key], 1.0, key)

    def test_reader_whatif_dominates_for_reader_bound_case(self) -> None:
        # Reader is the bulk of D_span which is the bulk of E2E.
        out = build_e2e_prediction(
            _inputs(B_pred=100_000.0, R_pred=6_000_000.0, D_span_pred=6_000_000.0)
        )
        self.assertGreater(out["whatif_halve_reader_time_speedup"], 1.4)
        self.assertGreater(
            out["whatif_halve_reader_time_speedup"],
            out["whatif_halve_b_repeated_scans_speedup"],
        )

    def test_optional_d_whatifs_emitted_when_supplied(self) -> None:
        out = build_e2e_prediction(
            _inputs(d_whatif_cycles={"full_sweep_half": 4_000_000.0,
                                     "replay_to_clipped": 3_000_000.0})
        )
        self.assertGreater(out["whatif_halve_d_full_tile_sweep_speedup"], 1.0)
        self.assertGreater(out["whatif_halve_d_replay_speedup"], 1.0)

    def test_bottleneck_actual_and_pred_present(self) -> None:
        out = build_e2e_prediction(
            _inputs(B_actual=100, R_actual=95_00_000, D_span_actual=10_000_000,
                    B_pred=100, R_pred=9_500_000, D_span_pred=10_000_000)
        )
        self.assertEqual(out["bottleneck_actual"], "reader_dominant")
        self.assertEqual(out["bottleneck_pred"], "reader_dominant")


class ShapingTests(unittest.TestCase):
    def test_prediction_has_all_columns(self) -> None:
        out = build_e2e_prediction(
            _inputs(d_whatif_cycles={"full_sweep_half": 4_000_000.0,
                                     "replay_to_clipped": 3_000_000.0})
        )
        for field in E2E_PREDICTION_FIELD_ORDER:
            self.assertIn(field, out, field)

    def test_evidence_note_flags_tiny_and_holdout(self) -> None:
        out = build_e2e_prediction(_inputs(batch_edges=10.0, jitter_pct=9.0, role="holdout"))
        note = out["evidence_note"]
        self.assertIn("tiny_case_edges_lt_512", note)
        self.assertIn("high_jitter", note)
        self.assertIn("holdout", note)

    def test_group_summary_targets(self) -> None:
        preds = [
            build_e2e_prediction(_inputs(case="a", role="holdout")),
            build_e2e_prediction(_inputs(case="b", role="holdout")),
        ]
        summaries = e2e_group_summary(preds)
        targets = {(s["validation_kind"], s["target"]) for s in summaries}
        self.assertEqual(
            targets,
            {("e2e", "B"), ("e2e", "R"), ("e2e", "D_span"), ("e2e", "serial")},
        )

    def test_group_summary_appends_component_rows(self) -> None:
        preds = [build_e2e_prediction(_inputs(role="holdout"))]
        extra = [component_summary_row("B", "phase2b", "calibration", [0.1, 0.2, 0.3])]
        summaries = e2e_group_summary(preds, extra_component_rows=extra)
        component = [s for s in summaries if s["validation_kind"] == "component"]
        self.assertEqual(len(component), 1)
        self.assertEqual(component[0]["target"], "B")
        self.assertEqual(component[0]["cases"], 3)

    def test_field_order_is_stable_list(self) -> None:
        self.assertEqual(e2e_prediction_field_order()[0], "group")
        self.assertIn("serial_error_pct", e2e_prediction_field_order())


class RealEvidenceIntegrationTests(unittest.TestCase):
    """Fit the reader model on real evidence when the directories are present."""

    def _available(self) -> bool:
        return (
            ROOT / "results/phase4a_amazon_exact_slices_hw_20260719_224034/summary.csv"
        ).exists()

    def test_reader_model_fits_real_slices(self) -> None:
        if not self._available():
            self.skipTest("real evidence not present")
        from scripts.analyze_hw_dstage_tile_timing import load_dataset, numeric

        exact = load_dataset(
            ROOT / "results/phase4a_amazon_exact_slices_hw_20260719_224034"
        )
        reallike = load_dataset(
            ROOT / "results/phase3d_amazon_slices_hw_20260719_220659"
        )
        cal_cases = {
            "amazon_top512_exact",
            "amazon_top8192_exact",
            "amazon_densewin4096_active3933_exact",
            "amazon_stride512_exact",
        }
        calibration = reallike + [r for r in exact if str(r["case"]) in cal_cases]
        model = fit_reader_model(calibration, freq_mhz=FREQ)
        # Non-tiny holdout slices should be within a diagnostic tolerance.
        errors = []
        for row in exact:
            if str(row["case"]) in cal_cases:
                continue
            if (numeric(row, "median_input_edges") or 0.0) < 512:
                continue
            actual = numeric(row, "median_reader_ms") * FREQ * 1000.0
            pred = model.predict(row)
            errors.append(abs(pred - actual) / actual * 100.0)
        errors.sort()
        median = errors[len(errors) // 2]
        self.assertLess(median, 25.0)


if __name__ == "__main__":
    unittest.main()
