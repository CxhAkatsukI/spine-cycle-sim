import math
import unittest

from spine_cycle_sim.calibration.current_fpga import (
    CurrentFPGAComposedRecord,
    CurrentFPGAComponentRecord,
    CurrentFPGAOverlapRecord,
    CurrentFPGATimingRecord,
    absolute_error_percent,
    composed_prediction_rows,
    component_prediction_rows,
    fit_component_scale,
    fit_composed_timing_model,
    fit_overlap_timing_model,
    fit_total_scale,
    overlap_leave_one_dataset_out_rows,
    overlap_prediction_rows,
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

    def test_composed_scale_only_supports_one_propagating_calibration_row(self):
        rows = [
            CurrentFPGAComposedRecord(
                "spine", "respr", "p1", "zero1", "calibration", 10, 0, 0, 30, 0
            ),
            CurrentFPGAComposedRecord(
                "spine", "respr", "p1", "zero2", "calibration", 20, 0, 0, 60, 0
            ),
            CurrentFPGAComposedRecord(
                "spine", "respr", "p1", "prop", "calibration", 30, 100, 2, 90, 500
            ),
            CurrentFPGAComposedRecord(
                "spine", "respr", "p1", "holdout", "holdout", 40, 200, 1, 120, 1000
            ),
        ]
        model = fit_composed_timing_model(
            rows, iterative_strategy="simulator_scale_only"
        )
        self.assertEqual(model.iterative_strategy, "simulator_scale_only")
        self.assertEqual(model.iterative_fixed_cycles_per_iteration, 0.0)
        self.assertAlmostEqual(model.iterative_simulator_scale, 5.0)
        self.assertAlmostEqual(
            model.predict_components(40, 200, 1)["total_cycles"], 1120.0
        )

    def test_composed_model_recovers_fixed_maintenance_shell(self):
        rows = [
            CurrentFPGAComposedRecord(
                "spine", "respr", "p1", dataset, role, maintenance, 0, 0,
                100 + 2 * maintenance, 0,
            )
            for dataset, role, maintenance in (
                ("au", "calibration", 10),
                ("su", "calibration", 20),
                ("so", "calibration", 40),
                ("lj", "holdout", 30),
            )
        ]
        rows.append(
            CurrentFPGAComposedRecord(
                "spine", "respr", "p1", "prop", "calibration", 50, 10, 1,
                200, 20,
            )
        )
        model = fit_composed_timing_model(
            rows, iterative_strategy="simulator_scale_only"
        )
        self.assertAlmostEqual(model.maintenance_fixed_cycles, 100.0)
        self.assertAlmostEqual(model.maintenance_scale, 2.0)
        self.assertAlmostEqual(
            model.predict_components(30, 0, 0)["maintenance_cycles"], 160.0
        )

    def test_sssp_realized_work_model_recovers_three_terms(self):
        def row(dataset, role, maintenance, span, checks, requests):
            target = 2 * span + 3 * checks + 5 * requests
            return CurrentFPGAComposedRecord(
                "spine", "sssp", "p1", dataset, role, maintenance, span, 1,
                10 + maintenance, target, checks, requests, 0,
            )

        rows = [
            row("au", "calibration", 10, 100, 10, 5),
            row("su", "calibration", 20, 50, 40, 10),
            row("so", "calibration", 30, 20, 5, 50),
            row("pk", "calibration", 40, 80, 30, 20),
            row("lj", "holdout", 25, 70, 20, 15),
        ]
        model = fit_composed_timing_model(
            rows, iterative_strategy="hls_sssp_realized_work"
        )
        self.assertAlmostEqual(model.iterative_simulator_scale, 2.0)
        self.assertAlmostEqual(model.iterative_level_check_cycles, 3.0)
        self.assertAlmostEqual(model.iterative_memory_request_cycles, 5.0)
        prediction = model.predict_components(25, 70, 1, 20, 15, 0)
        self.assertAlmostEqual(prediction["iterative_cycles"], 275.0)

    def test_cc_realized_work_model_recovers_protocol_and_hot_state_terms(self):
        def row(dataset, role, maintenance, iterations, requests, hot_vertices):
            return CurrentFPGAComposedRecord(
                "spine", "cc", "p1", dataset, role, maintenance, 10, iterations,
                20 + maintenance,
                100 * iterations + 7 * requests + 3 * hot_vertices * iterations,
                simulator_reader_parent_requests=requests,
                simulator_hot_vertex_iterations=hot_vertices * iterations,
            )

        rows = [
            row("au", "calibration", 10, 1, 10, 0),
            row("su", "calibration", 20, 1, 20, 5),
            row("so", "calibration", 30, 1, 40, 1),
            row("pk", "calibration", 40, 2, 30, 10),
            row("lj", "holdout", 25, 2, 30, 4),
        ]
        model = fit_composed_timing_model(
            rows, iterative_strategy="hls_cc_realized_work"
        )
        self.assertAlmostEqual(model.iterative_fixed_cycles_per_iteration, 100.0)
        self.assertAlmostEqual(model.iterative_reader_parent_request_cycles, 7.0)
        self.assertAlmostEqual(model.iterative_hot_vertex_cycles, 3.0)
        prediction = model.predict_components(25, 10, 2, 0, 0, 0, 30, 8)
        self.assertAlmostEqual(prediction["iterative_cycles"], 434.0)

    def test_overlap_model_recovers_reader_compute_and_span_terms(self):
        def row(dataset, role, values):
            (
                maintenance,
                reader,
                compute,
                requests,
                cache,
                reader_tasks,
                credit_stalls,
                scan,
                compute_tasks,
                edges,
                iterations,
                vertices,
            ) = values
            hardware_maintenance = 100 + 2 * maintenance
            hardware_reader = 2 * requests + 3 * iterations + 5 * vertices
            hardware_compute = 7 * iterations + 11 * compute_tasks + 13 * edges
            hardware_span = max(hardware_reader, hardware_compute) + 17 * iterations
            return CurrentFPGAOverlapRecord(
                "spine",
                "sssp",
                "p1",
                dataset,
                role,
                iterations,
                vertices,
                maintenance,
                reader,
                compute,
                requests,
                cache,
                reader_tasks,
                credit_stalls,
                scan,
                compute_tasks,
                edges,
                hardware_maintenance,
                hardware_reader,
                hardware_compute,
                hardware_span,
            )

        rows = [
            row("au", "calibration", (10, 11, 13, 17, 19, 23, 29, 31, 37, 41, 1, 43)),
            row("su", "calibration", (20, 31, 37, 41, 43, 47, 53, 59, 61, 67, 2, 71)),
            row("so", "calibration", (30, 59, 61, 67, 71, 73, 79, 83, 89, 97, 1, 101)),
            row("pk", "calibration", (40, 83, 89, 97, 101, 103, 107, 109, 113, 127, 3, 131)),
            row("wk", "calibration", (50, 109, 113, 127, 131, 137, 139, 149, 151, 157, 2, 163)),
            row("hold", "holdout", (25, 43, 47, 53, 59, 61, 67, 71, 73, 79, 2, 83)),
        ]
        model = fit_overlap_timing_model(rows)
        self.assertAlmostEqual(model.maintenance_fixed_cycles, 100.0)
        self.assertAlmostEqual(model.maintenance_scale, 2.0)
        self.assertAlmostEqual(model.reader_memory_request_cycles, 2.0)
        self.assertAlmostEqual(model.reader_round_cycles, 3.0)
        self.assertAlmostEqual(model.reader_vertex_cycles, 5.0)
        self.assertAlmostEqual(model.compute_round_cycles, 7.0)
        self.assertAlmostEqual(model.compute_range_task_cycles, 11.0)
        self.assertAlmostEqual(model.compute_processed_edge_cycles, 13.0)
        self.assertAlmostEqual(model.span_residual_cycles_per_iteration, 17.0)
        predictions = overlap_prediction_rows(rows, model)
        self.assertEqual(predictions[-1]["role"], "holdout")
        self.assertAlmostEqual(predictions[-1]["total_absolute_error_percent"], 0.0)

        prediction = model.predict_components(
            iterations=1,
            simulator_vertices=1,
            simulator_maintenance_cycles=1,
            simulator_reader_cycles=1,
            simulator_compute_cycles=1,
            simulator_reader_memory_requests=0,
            simulator_reader_level_cache_words=0,
            simulator_reader_range_tasks=0,
            simulator_reader_credit_stall_cycles=0,
            simulator_compute_active_scan_words=0,
            simulator_compute_range_tasks=0,
            simulator_processed_edges=0,
        )
        self.assertGreater(prediction["total_cycles"], 0)

        leave_one_out = overlap_leave_one_dataset_out_rows(rows)
        self.assertEqual(len(leave_one_out), 5)
        self.assertEqual(
            {item["held_out_dataset"] for item in leave_one_out},
            {"au", "su", "so", "pk", "wk"},
        )
        self.assertTrue(
            all(item["role"] == "leave_one_out" for item in leave_one_out)
        )
        self.assertTrue(
            all(item["total_absolute_error_percent"] < 1e-8 for item in leave_one_out)
        )

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
