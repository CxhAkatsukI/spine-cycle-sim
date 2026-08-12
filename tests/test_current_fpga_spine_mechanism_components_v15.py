import unittest

from spine_cycle_sim.calibration.current_fpga import (
    SpineMechanismComponentRecord,
    fit_spine_mechanism_component_model,
    spine_mechanism_component_prediction_rows,
)


class CurrentFPGASpineMechanismComponentsV15Tests(unittest.TestCase):
    def iterative_rows(self):
        rows = []
        features = (
            ("a", 1, 100, 7, 20),
            ("b", 2, 220, 23, 35),
            ("c", 2, 310, 11, 65),
            ("d", 1, 470, 37, 90),
        )
        for index, (
            dataset,
            rounds,
            vertices,
            reader_requests,
            simulator_compute,
        ) in enumerate(features, 1):
            maintenance = 10 * index
            hardware_maintenance = 30 + 2 * maintenance
            hardware_reader = (
                11 * rounds + 3 * vertices + 5 * reader_requests
            )
            hardware_compute = 13 * rounds + 7 * simulator_compute
            hardware_span = max(hardware_reader, hardware_compute) + 17 * rounds
            rows.append(
                SpineMechanismComponentRecord(
                    "weighted_sssp",
                    "p",
                    dataset,
                    "calibration",
                    rounds,
                    vertices,
                    maintenance,
                    99 * index,
                    simulator_compute,
                    reader_requests,
                    2 * reader_requests,
                    hardware_maintenance,
                    hardware_reader,
                    hardware_compute,
                    hardware_span,
                )
            )
        return rows

    def test_recovers_non_overlapping_hls_terms(self):
        rows = self.iterative_rows()
        model = fit_spine_mechanism_component_model(rows)
        self.assertAlmostEqual(model.maintenance_fixed_cycles, 30.0)
        self.assertAlmostEqual(model.maintenance_simulator_scale, 2.0)
        self.assertAlmostEqual(model.reader_round_cycles, 11.0)
        self.assertAlmostEqual(model.reader_vertex_cycles, 3.0)
        self.assertAlmostEqual(model.reader_memory_request_cycles, 5.0)
        self.assertEqual(model.compute_fixed_cycles, 0.0)
        self.assertAlmostEqual(model.compute_round_cycles, 13.0)
        self.assertEqual(model.compute_memory_request_cycles, 0.0)
        self.assertAlmostEqual(model.compute_simulator_cycle_scale, 7.0)
        self.assertAlmostEqual(model.span_residual_cycles_per_round, 17.0)
        predictions = spine_mechanism_component_prediction_rows(rows, model)
        self.assertTrue(
            all(row["total_absolute_error_percent"] < 1e-8 for row in predictions)
        )

    def test_freeze_rejects_holdout_targets(self):
        rows = self.iterative_rows()
        rows[-1] = SpineMechanismComponentRecord(
            **{**rows[-1].__dict__, "role": "holdout"}
        )
        with self.assertRaisesRegex(ValueError, "rejects non-calibration"):
            fit_spine_mechanism_component_model(rows)

    def test_reader_does_not_double_count_simulator_span(self):
        rows = self.iterative_rows()
        model = fit_spine_mechanism_component_model(rows)
        baseline = model.predict_components(
            rounds=1,
            vertices=100,
            simulator_maintenance_cycles=10,
            simulator_reader_cycles=100,
            simulator_compute_cycles=20,
            simulator_reader_memory_requests=7,
            simulator_compute_memory_requests=14,
        )
        changed = model.predict_components(
            rounds=1,
            vertices=100,
            simulator_maintenance_cycles=10,
            simulator_reader_cycles=100000,
            simulator_compute_cycles=20,
            simulator_reader_memory_requests=7,
            simulator_compute_memory_requests=14,
        )
        self.assertEqual(baseline["reader_cycles"], changed["reader_cycles"])

    def test_cc_strategy_can_retain_state_request_service(self):
        rows = []
        for row in self.iterative_rows():
            hardware_compute = (
                13 * row.rounds
                + 4 * row.simulator_compute_memory_requests
                + 7 * row.simulator_compute_cycles
            )
            rows.append(
                SpineMechanismComponentRecord(
                    **{
                        **row.__dict__,
                        "algorithm": "connected_components",
                        "hardware_compute_cycles": hardware_compute,
                        "hardware_iterative_span_cycles": max(
                            row.hardware_reader_cycles, hardware_compute
                        )
                        + 17 * row.rounds,
                    }
                )
            )
        model = fit_spine_mechanism_component_model(
            rows, compute_strategy="request_plus_execution"
        )
        self.assertAlmostEqual(model.compute_round_cycles, 13.0)
        self.assertAlmostEqual(model.compute_memory_request_cycles, 4.0)
        self.assertAlmostEqual(model.compute_simulator_cycle_scale, 7.0)

    def test_fixed_compute_strategy_recovers_event_launch_cost(self):
        rows = []
        for row in self.iterative_rows():
            hardware_compute = 41 + 7 * row.simulator_compute_cycles
            rows.append(
                SpineMechanismComponentRecord(
                    **{
                        **row.__dict__,
                        "hardware_compute_cycles": hardware_compute,
                        "hardware_iterative_span_cycles": max(
                            row.hardware_reader_cycles, hardware_compute
                        )
                        + 17 * row.rounds,
                    }
                )
            )
        model = fit_spine_mechanism_component_model(
            rows, compute_strategy="fixed_plus_execution"
        )
        self.assertAlmostEqual(model.compute_fixed_cycles, 41.0)
        self.assertEqual(model.compute_round_cycles, 0.0)
        self.assertAlmostEqual(model.compute_simulator_cycle_scale, 7.0)

    def test_zero_round_algorithm_is_maintenance_only(self):
        rows = [
            SpineMechanismComponentRecord(
                "thresholded_residual_pagerank",
                "p",
                dataset,
                "calibration",
                0,
                100 * index,
                10 * index,
                0,
                0,
                0,
                0,
                20 + 3 * 10 * index,
                0,
                0,
                0,
            )
            for index, dataset in enumerate(("a", "b", "c", "d"), 1)
        ]
        model = fit_spine_mechanism_component_model(rows)
        prediction = model.predict_components(
            rounds=0,
            vertices=500,
            simulator_maintenance_cycles=50,
            simulator_reader_cycles=0,
            simulator_compute_cycles=0,
            simulator_reader_memory_requests=0,
            simulator_compute_memory_requests=0,
        )
        self.assertAlmostEqual(prediction["total_cycles"], 170.0)
        self.assertEqual(prediction["iterative_span_cycles"], 0.0)


if __name__ == "__main__":
    unittest.main()
