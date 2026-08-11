import math
import unittest

from spine_cycle_sim.calibration.current_fpga import (
    CurrentFPGAComposedRecord,
    CurrentFPGAComponentRecord,
    CurrentFPGATimingRecord,
    absolute_error_percent,
    composed_prediction_rows,
    component_prediction_rows,
    fit_component_scale,
    fit_composed_timing_model,
    fit_total_scale,
    spearman_rank_correlation,
    total_prediction_rows,
)


class CurrentFPGACalibrationTests(unittest.TestCase):
    def timing_rows(self):
        return [
            CurrentFPGATimingRecord("spine", "sssp", "p1", "au", "calibration", 10, 20),
            CurrentFPGATimingRecord("spine", "sssp", "p1", "su", "calibration", 40, 80),
            CurrentFPGATimingRecord("spine", "sssp", "p1", "wk", "holdout", 30, 60),
            CurrentFPGATimingRecord("spine", "sssp", "p1", "r19", "holdout", 20, 40),
        ]

    def component_rows(self):
        return [
            CurrentFPGAComponentRecord(
                "spine", "sssp", "p1", "au", "calibration", "reader", 10, 30,
                "median routed reader event; overlaps compute",
            ),
            CurrentFPGAComponentRecord(
                "spine", "sssp", "p1", "su", "calibration", "reader", 20, 60,
                "median routed reader event; overlaps compute",
            ),
            CurrentFPGAComponentRecord(
                "spine", "sssp", "p1", "wk", "holdout", "reader", 30, 90,
                "median routed reader event; overlaps compute",
            ),
        ]

    def composed_rows(self):
        # Hardware iterative = 100 cycles/round + 2 * simulator iterative.
        return [
            CurrentFPGAComposedRecord(
                "spine", "sssp", "p1", "au", "calibration", 10, 100, 1, 30, 300
            ),
            CurrentFPGAComposedRecord(
                "spine", "sssp", "p1", "su", "calibration", 20, 300, 2, 60, 800
            ),
            CurrentFPGAComposedRecord(
                "spine", "sssp", "p1", "so", "calibration", 30, 50, 3, 90, 400
            ),
            CurrentFPGAComposedRecord(
                "spine", "sssp", "p1", "wk", "development_validation", 40, 200, 2,
                120, 600,
            ),
            CurrentFPGAComposedRecord(
                "spine", "sssp", "p1", "lj", "holdout", 50, 400, 4, 150, 1200
            ),
        ]

    def test_total_scale_uses_calibration_only(self):
        rows = self.timing_rows()
        model = fit_total_scale(rows)
        self.assertAlmostEqual(model.scale, 2.0)
        changed_holdout = [
            row if row.role == "calibration" else CurrentFPGATimingRecord(
                row.architecture, row.algorithm, row.profile_id, row.dataset,
                row.role, row.simulator_cycles, row.hardware_cycles * 100,
            )
            for row in rows
        ]
        self.assertAlmostEqual(fit_total_scale(changed_holdout).scale, model.scale)

    def test_total_predictions_preserve_roles(self):
        rows = self.timing_rows()
        predictions = total_prediction_rows(rows, fit_total_scale(rows))
        self.assertEqual([row["role"] for row in predictions].count("holdout"), 2)
        self.assertTrue(all(row["absolute_error_percent"] == 0 for row in predictions))

    def test_component_scale_requires_observation_scope(self):
        rows = self.component_rows()
        bad = [
            CurrentFPGAComponentRecord(
                row.architecture, row.algorithm, row.profile_id, row.dataset,
                row.role, row.component, row.simulator_cycles,
                row.hardware_cycles, "",
            )
            for row in rows
        ]
        with self.assertRaisesRegex(ValueError, "observation scope"):
            fit_component_scale(bad)

    def test_component_predictions(self):
        rows = self.component_rows()
        model = fit_component_scale(rows)
        self.assertAlmostEqual(model.scale, 3.0)
        predictions = component_prediction_rows(rows, model)
        self.assertTrue(
            all(
                math.isclose(row["absolute_error_percent"], 0.0, abs_tol=1e-12)
                for row in predictions
            )
        )

    def test_composed_model_recovers_hls_fixed_and_execution_terms(self):
        rows = self.composed_rows()
        model = fit_composed_timing_model(rows)
        self.assertAlmostEqual(model.maintenance_scale, 3.0)
        self.assertAlmostEqual(model.iterative_fixed_cycles_per_iteration, 100.0)
        self.assertAlmostEqual(model.iterative_simulator_scale, 2.0)
        predictions = composed_prediction_rows(rows, model)
        self.assertTrue(
            all(
                math.isclose(row["total_absolute_error_percent"], 0.0, abs_tol=1e-10)
                for row in predictions
            )
        )

    def test_composed_model_ignores_validation_and_holdout_targets(self):
        rows = self.composed_rows()
        baseline = fit_composed_timing_model(rows)
        changed = [
            row
            if row.role == "calibration"
            else CurrentFPGAComposedRecord(
                row.architecture,
                row.algorithm,
                row.profile_id,
                row.dataset,
                row.role,
                row.simulator_maintenance_cycles,
                row.simulator_iterative_cycles,
                row.iterations,
                row.hardware_maintenance_cycles * 100,
                row.hardware_iterative_cycles * 100,
            )
            for row in rows
        ]
        observed = fit_composed_timing_model(changed)
        self.assertEqual(observed, baseline)

    def test_composed_zero_propagation_is_maintenance_only(self):
        model = fit_composed_timing_model(self.composed_rows())
        prediction = model.predict_components(12, 0, 0)
        self.assertAlmostEqual(prediction["maintenance_cycles"], 36.0)
        self.assertEqual(prediction["iterative_cycles"], 0.0)
        self.assertAlmostEqual(prediction["total_cycles"], 36.0)

    def test_composed_model_rejects_dataset_role_overlap(self):
        rows = self.composed_rows()
        rows[-1] = CurrentFPGAComposedRecord(
            "spine", "sssp", "p1", "au", "holdout", 50, 400, 4, 150, 1200
        )
        with self.assertRaisesRegex(ValueError, "overlap"):
            fit_composed_timing_model(rows)

    def test_composed_model_rejects_zero_iteration_work(self):
        rows = self.composed_rows()
        rows[0] = CurrentFPGAComposedRecord(
            "spine", "sssp", "p1", "au", "calibration", 10, 1, 0, 30, 0
        )
        with self.assertRaisesRegex(ValueError, "zero-iteration"):
            fit_composed_timing_model(rows)

    def test_roles_must_be_disjoint(self):
        rows = self.timing_rows()
        rows[-1] = CurrentFPGATimingRecord(
            "spine", "sssp", "p1", "au", "holdout", 20, 40
        )
        with self.assertRaisesRegex(ValueError, "overlap"):
            fit_total_scale(rows)

    def test_non_positive_cycles_are_rejected(self):
        rows = self.timing_rows()
        rows[0] = CurrentFPGATimingRecord(
            "spine", "sssp", "p1", "au", "calibration", 0, 20
        )
        with self.assertRaisesRegex(ValueError, "positive"):
            fit_total_scale(rows)

    def test_spearman_with_ties(self):
        self.assertTrue(math.isclose(spearman_rank_correlation([1, 2, 3], [2, 4, 8]), 1.0))
        self.assertTrue(math.isclose(spearman_rank_correlation([1, 2, 3], [8, 4, 2]), -1.0))
        self.assertGreater(spearman_rank_correlation([1, 1, 3], [2, 2, 8]), 0.99)

    def test_absolute_error_percent(self):
        self.assertAlmostEqual(absolute_error_percent(90, 100), 10.0)


if __name__ == "__main__":
    unittest.main()
