import unittest

from spine_cycle_sim.calibration.current_fpga import (
    SpineComponentFeatureRecord,
    fit_spine_component_feature_model,
    spine_component_feature_leave_one_dataset_out_rows,
    spine_component_feature_prediction_rows,
)


class CurrentFPGASpineComponentFeaturesV14Tests(unittest.TestCase):
    def iterative_rows(self):
        rows = []
        for index, dataset in enumerate(("au", "su", "wk", "r19", "pk", "so"), 1):
            rounds = 1 + index % 3
            maintenance = 20 + 7 * index
            reader_cycles = 31 + 13 * index + index * index
            compute_cycles = 37 + 17 * index + 2 * index * index
            reader_requests = 11 + 5 * index + 3 * index * index
            compute_requests = 13 + 7 * index + index * index
            hardware_maintenance = 100 + 2 * maintenance
            hardware_reader = 3 * reader_requests + 5 * reader_cycles
            hardware_compute = (
                7 * rounds + 11 * compute_requests + 13 * compute_cycles
            )
            hardware_span = max(hardware_reader, hardware_compute) + 17 * rounds
            rows.append(
                SpineComponentFeatureRecord(
                    "weighted_sssp",
                    "spine-owner-v1",
                    dataset,
                    "calibration",
                    rounds,
                    maintenance,
                    reader_cycles,
                    compute_cycles,
                    reader_requests,
                    compute_requests,
                    hardware_maintenance,
                    hardware_reader,
                    hardware_compute,
                    hardware_span,
                )
            )
        return rows

    def test_fit_recovers_component_and_overlap_terms(self):
        rows = self.iterative_rows()
        model = fit_spine_component_feature_model(rows)
        self.assertAlmostEqual(model.maintenance_fixed_cycles, 100.0)
        self.assertAlmostEqual(model.maintenance_simulator_scale, 2.0)
        self.assertAlmostEqual(model.reader_memory_request_cycles, 3.0)
        self.assertAlmostEqual(model.reader_simulator_cycle_scale, 5.0)
        self.assertAlmostEqual(model.compute_round_cycles, 7.0)
        self.assertAlmostEqual(model.compute_memory_request_cycles, 11.0)
        self.assertAlmostEqual(model.compute_simulator_cycle_scale, 13.0)
        self.assertAlmostEqual(model.span_residual_cycles_per_round, 17.0)
        predictions = spine_component_feature_prediction_rows(rows, model)
        self.assertTrue(
            all(row["total_absolute_error_percent"] < 1e-8 for row in predictions)
        )

    def test_fit_rejects_holdout_rows(self):
        rows = self.iterative_rows()
        rows[-1] = SpineComponentFeatureRecord(
            **{**rows[-1].__dict__, "role": "holdout"}
        )
        with self.assertRaisesRegex(ValueError, "rejects non-calibration"):
            fit_spine_component_feature_model(rows)

    def test_zero_round_model_is_maintenance_only(self):
        rows = [
            SpineComponentFeatureRecord(
                "thresholded_residual_pagerank",
                "spine-respr-v1",
                dataset,
                "calibration",
                0,
                maintenance,
                0,
                0,
                0,
                0,
                50 + 4 * maintenance,
                0,
                0,
                0,
            )
            for dataset, maintenance in zip(
                ("au", "su", "wk", "r19", "pk"), (10, 20, 30, 40, 50)
            )
        ]
        model = fit_spine_component_feature_model(rows)
        prediction = model.predict_components(
            rounds=0,
            simulator_maintenance_cycles=60,
            simulator_reader_cycles=0,
            simulator_compute_cycles=0,
            simulator_reader_memory_requests=0,
            simulator_compute_memory_requests=0,
        )
        self.assertAlmostEqual(prediction["total_cycles"], 290.0)
        self.assertEqual(prediction["iterative_span_cycles"], 0.0)

    def test_leave_one_dataset_out_does_not_fit_held_row(self):
        rows = self.iterative_rows()
        predictions = spine_component_feature_leave_one_dataset_out_rows(rows)
        self.assertEqual(len(predictions), len(rows))
        for prediction in predictions:
            self.assertNotIn(
                prediction["held_out_dataset"],
                prediction["training_datasets"].split(";"),
            )
            self.assertLess(prediction["total_absolute_error_percent"], 1e-8)

    def test_zero_round_prediction_rejects_hidden_iterative_work(self):
        rows = [
            SpineComponentFeatureRecord(
                "thresholded_residual_pagerank",
                "spine-respr-v1",
                dataset,
                "calibration",
                0,
                maintenance,
                0,
                0,
                0,
                0,
                50 + 4 * maintenance,
                0,
                0,
                0,
            )
            for dataset, maintenance in zip(
                ("au", "su", "wk", "r19"), (10, 20, 30, 40)
            )
        ]
        model = fit_spine_component_feature_model(rows)
        with self.assertRaisesRegex(ValueError, "zero-round"):
            model.predict_components(
                rounds=0,
                simulator_maintenance_cycles=20,
                simulator_reader_cycles=1,
                simulator_compute_cycles=0,
                simulator_reader_memory_requests=0,
                simulator_compute_memory_requests=0,
            )


if __name__ == "__main__":
    unittest.main()
