from __future__ import annotations

import unittest
from pathlib import Path

from spine_cycle_sim.calibration import (
    READER_COMPONENT_ORDER,
    READER_WHATIF_ORDER,
    fit_reader_component_model,
    load_reader_rows,
    reader_component_model_to_dict,
    reader_feature_values,
    reader_group_summary,
    reader_prediction_field_order,
    reader_prediction_row,
)
from spine_cycle_sim.calibration.reader import path_class

ROOT = Path(__file__).resolve().parents[1]
FREQ = 134.0


def _row(reader_cycles, *, edges=0.0, replay=0.0, fast=0.0, full=0.0,
         fallback_count=0.0, clipped=0.0, partitions=1.0, fast_count=0.0,
         full_count=0.0, case="c", conv_span_cycles=None, kernel_cycles=None):
    return {
        "case": case,
        "sweep": "reader_axis",
        "median_reader_ms": reader_cycles / (FREQ * 1000.0),
        "median_conv_span_ms": (conv_span_cycles or reader_cycles) / (FREQ * 1000.0),
        "median_kernel_e2e_ms": (kernel_cycles or reader_cycles) / (FREQ * 1000.0),
        "median_traversed_edges": edges,
        "median_active_records": replay,
        "median_touched_tiles": 1.0,
        "active_records_x_touched_tiles": replay,
        "tile_fast_gathered_words": fast,
        "tile_scattered_words": 0.0,
        "tile_full_swept_words": full,
        "tile_fallback_count": fallback_count,
        "tile_clipped_ranges": clipped,
        "tile_partition_count": partitions,
        "tile_fast_count": fast_count,
        "tile_full_count": full_count,
        "conv_ms_jitter_pct": 0.1,
    }


class FeatureExtractionTests(unittest.TestCase):
    def test_reader_feature_values(self) -> None:
        row = _row(1_000_000, edges=4096, replay=100, fast=50, full=200,
                   fallback_count=2, clipped=10, partitions=4)
        values = reader_feature_values(row)
        self.assertEqual(values["fixed"], 1.0)
        self.assertEqual(values["edge_stream"], 4096.0)
        self.assertEqual(values["active_record_replay"], 100.0)
        self.assertEqual(values["fast_gather_scatter"], 50.0)
        self.assertEqual(values["full_sweep"], 200.0)
        self.assertEqual(values["fallback"], 20.0)  # 2 * 10
        self.assertEqual(values["partition_spread"], 4.0)

    def test_path_class(self) -> None:
        self.assertEqual(path_class(_row(1, fallback_count=1)), "fallback")
        self.assertEqual(path_class(_row(1, fast_count=1, full_count=1)), "mixed")
        self.assertEqual(path_class(_row(1, full_count=1)), "full_only")
        self.assertEqual(path_class(_row(1, fast_count=1)), "fast_only")
        self.assertEqual(path_class(_row(1)), "none")


class FitTests(unittest.TestCase):
    def _synthetic_rows(self):
        # reader_cycles = 100000 + 5*edges + 1000*replay (exact, non-negative).
        rows = []
        for edges, replay in [
            (0, 0), (1000, 0), (4000, 0), (8000, 0),
            (0, 10), (0, 50), (0, 100), (2000, 30), (6000, 80),
        ]:
            cycles = 100_000 + 5.0 * edges + 1000.0 * replay
            rows.append(_row(cycles, edges=edges, replay=replay, case=f"e{edges}_r{replay}"))
        return rows

    def test_recovers_nonnegative_coefficients(self) -> None:
        model = fit_reader_component_model(
            self._synthetic_rows(), freq_mhz=FREQ, weight_mode="none"
        )
        self.assertAlmostEqual(model.coefficients["fixed"], 100_000, delta=2000)
        self.assertAlmostEqual(model.coefficients["edge_stream"], 5.0, delta=0.3)
        self.assertAlmostEqual(model.coefficients["active_record_replay"], 1000.0, delta=30)

    def test_all_coefficients_non_negative(self) -> None:
        model = fit_reader_component_model(self._synthetic_rows(), freq_mhz=FREQ)
        for name, value in model.coefficients.items():
            self.assertGreaterEqual(value, 0.0, name)

    def test_unused_features_stay_zero(self) -> None:
        model = fit_reader_component_model(
            self._synthetic_rows(), freq_mhz=FREQ, weight_mode="none"
        )
        # No fast/full/fallback/partition variance in the data.
        self.assertEqual(model.coefficients["fast_gather_scatter"], 0.0)
        self.assertEqual(model.coefficients["full_sweep"], 0.0)
        self.assertEqual(model.coefficients["fallback"], 0.0)

    def test_components_sum_to_predicted(self) -> None:
        model = fit_reader_component_model(self._synthetic_rows(), freq_mhz=FREQ)
        row = _row(500_000, edges=4000, replay=50)
        components = model.components(row)
        self.assertAlmostEqual(sum(components.values()), model.predicted_cycles(row), places=3)
        self.assertEqual(set(components), set(READER_COMPONENT_ORDER))


class WhatIfTests(unittest.TestCase):
    def setUp(self) -> None:
        rows = [
            _row(100_000 + 1000.0 * replay, replay=replay, case=f"r{replay}")
            for replay in [0, 10, 50, 100, 200]
        ]
        self.model = fit_reader_component_model(rows, freq_mhz=FREQ, weight_mode="none")

    def test_whatif_speedups_at_least_one(self) -> None:
        row = _row(1_000_000, replay=200)
        whatifs = self.model.whatifs(row)
        self.assertEqual(set(whatifs), set(READER_WHATIF_ORDER))
        for name, entry in whatifs.items():
            self.assertGreaterEqual(entry["speedup"], 1.0, name)

    def test_halve_replay_dominant_for_replay_bound_case(self) -> None:
        row = _row(1_000_000, replay=800)  # replay dominates
        whatifs = self.model.whatifs(row)
        self.assertGreater(whatifs["halve_active_record_replay"]["speedup"], 1.3)
        self.assertGreaterEqual(
            whatifs["halve_active_record_replay"]["speedup"],
            whatifs["halve_edge_stream"]["speedup"],
        )


class PredictionShapingTests(unittest.TestCase):
    def setUp(self) -> None:
        rows = [
            _row(100_000 + 1000.0 * replay + 5.0 * edges, edges=edges, replay=replay,
                 case=f"e{edges}_r{replay}")
            for edges, replay in [(0, 0), (4000, 0), (0, 100), (8000, 50), (2000, 200)]
        ]
        self.model = fit_reader_component_model(rows, freq_mhz=FREQ, weight_mode="none")

    def test_predict_returns_none_without_reader(self) -> None:
        row = dict(_row(1_000_000, replay=10))
        row["median_reader_ms"] = ""
        self.assertIsNone(self.model.predict(row, group="g", role="holdout"))

    def test_prediction_row_has_all_columns(self) -> None:
        prediction = self.model.predict(
            _row(1_000_000, edges=4000, replay=100, fast_count=1), group="g", role="holdout"
        )
        row = reader_prediction_row(prediction)
        order = reader_prediction_field_order()
        self.assertEqual(set(row), set(order))
        for name in READER_COMPONENT_ORDER:
            self.assertIn(f"comp_{name}_cycles", row)
            self.assertIn(f"comp_{name}_share", row)

    def test_component_shares_sum_to_one(self) -> None:
        prediction = self.model.predict(_row(900_000, replay=100), group="g", role="holdout")
        row = reader_prediction_row(prediction)
        total_share = sum(row[f"comp_{name}_share"] for name in READER_COMPONENT_ORDER)
        self.assertAlmostEqual(total_share, 1.0, places=6)

    def test_evidence_note_flags_measurement_window_and_holdout(self) -> None:
        prediction = self.model.predict(
            _row(1_000_000, edges=10, replay=100), group="g", role="holdout"
        )
        note = prediction["evidence_note"]
        self.assertIn("measurement_window", note)
        self.assertIn("tiny_case_edges_lt_512", note)
        self.assertIn("holdout", note)

    def test_reader_share_of_conv_span(self) -> None:
        prediction = self.model.predict(
            _row(500_000, replay=100, conv_span_cycles=1_000_000),
            group="g", role="holdout",
        )
        self.assertAlmostEqual(prediction["reader_share_of_conv_span"], 0.5, places=6)
        self.assertAlmostEqual(prediction["d_tail_cycles"], 500_000.0, places=3)

    def test_group_summary_reports_dominant_path(self) -> None:
        preds = [
            self.model.predict(_row(900_000, replay=100, fast_count=1), group="g", role="holdout"),
            self.model.predict(_row(500_000, replay=50, fast_count=1), group="g", role="holdout"),
        ]
        summaries = reader_group_summary(preds)
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["cases"], 2)
        self.assertEqual(summaries[0]["dominant_path_class"], "fast_only")


class ModelToDictTests(unittest.TestCase):
    def test_reports_form_and_unidentifiable_components(self) -> None:
        rows = [
            _row(100_000 + 1000.0 * replay, replay=replay, partitions=0.0)
            for replay in [0, 10, 50, 100]
        ]
        model = fit_reader_component_model(rows, freq_mhz=FREQ, weight_mode="none")
        payload = reader_component_model_to_dict(model)
        self.assertEqual(payload["target"], "median_reader_ms")
        self.assertIn("active_records_x_touched_tiles", payload["form"])
        self.assertIn("fallback", payload["not_separately_identifiable"])
        self.assertIn("partition_spread", payload["not_separately_identifiable"])
        self.assertIn("event duration", payload["measurement_window_note"])


class RealEvidenceIntegrationTests(unittest.TestCase):
    _CALIBRATION = [
        "results/dstage_phase3a4_replay_calibration_hw_20260719_155924",
        "results/phase3c_full_partition_calibration_hw_20260719_175201",
        "results/phase3b_bottleneck_synthetic_hw_20260719_172739",
    ]
    _REAL = "results/phase4a_amazon_exact_slices_hw_20260719_224034"

    def _available(self) -> bool:
        return (ROOT / self._REAL / "summary.csv").exists()

    def test_loader_derives_replay_feature(self) -> None:
        if not self._available():
            self.skipTest("real evidence not present")
        rows = load_reader_rows(ROOT / self._REAL)
        self.assertTrue(rows)
        self.assertTrue(all("active_records_x_touched_tiles" in row for row in rows))

    def test_structured_model_validates_real_slices(self) -> None:
        if not self._available():
            self.skipTest("real evidence not present")
        calibration = []
        for path in self._CALIBRATION:
            calibration.extend(load_reader_rows(ROOT / path))
        model = fit_reader_component_model(calibration, freq_mhz=FREQ)
        # All coefficients non-negative.
        for value in model.coefficients.values():
            self.assertGreaterEqual(value, 0.0)
        errors = []
        for row in load_reader_rows(ROOT / self._REAL):
            prediction = model.predict(row, group="phase4a", role="holdout_real")
            if prediction is None:
                continue
            if prediction["traversed_edges"] < 512:
                continue
            errors.append(prediction["abs_error_pct"])
        errors.sort()
        median = errors[len(errors) // 2]
        self.assertLess(median, 15.0)  # real reader-dominant slices are trusted


if __name__ == "__main__":
    unittest.main()
