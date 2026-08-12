from __future__ import annotations

import unittest

from scripts.calibrate_current_fpga_rq3_v15 import (
    calibrate_row,
    iterative_model_supported,
)
from spine_cycle_sim.calibration.current_fpga import SpineMechanismComponentModel


def model(*, iterative: bool) -> SpineMechanismComponentModel:
    return SpineMechanismComponentModel(
        algorithm="weighted_sssp" if iterative else "thresholded_residual_pagerank",
        profile_id="profile",
        calibration_datasets=("au", "su"),
        maintenance_fixed_cycles=10.0,
        maintenance_simulator_scale=2.0,
        reader_round_cycles=3.0 if iterative else 0.0,
        reader_vertex_cycles=0.0,
        reader_memory_request_cycles=1.0 if iterative else 0.0,
        compute_fixed_cycles=0.0,
        compute_round_cycles=0.0,
        compute_memory_request_cycles=0.0,
        compute_simulator_cycle_scale=1.0 if iterative else 0.0,
        compute_strategy="fixed_plus_execution",
        span_residual_cycles_per_round=0.0,
    )


def ledger_row() -> dict[str, object]:
    return {
        "execution_id": "row",
        "total_cycles": 100,
        "ten_stage_supported": "True",
        "ten_stage_ledger_closed": "True",
        "t_xfer_cycles": 10,
        "t_reduce_cycles": 10,
        "t_carry_cycles": 0,
        "t_directory_cycles": 0,
        "t_seed_cycles": 0,
        "t_switch_cycles": 0,
        "t_resolve_cycles": 20,
        "t_app_cycles": 40,
        "t_drain_cycles": 20,
        "t_sync_cycles": 0,
    }


def raw_result() -> dict[str, object]:
    return {
        "vertices": 8,
        "rounds": 1,
        "maintenance_cycles": 10,
        "reader_active_cycles_per_round": [5],
        "reader_memory_requests_issued_per_round": [2],
        "reader_memory_requests_completed_per_round": [2],
        "compute_active_cycles_per_round": [7],
        "compute_memory_requests_issued_per_round": [1],
        "compute_memory_requests_completed_per_round": [1],
    }


class CurrentFPGARQ3V15CalibrationTests(unittest.TestCase):
    def test_supported_model_projects_component_envelopes(self) -> None:
        calibrated = calibrate_row(ledger_row(), raw_result(), model(iterative=True))

        self.assertEqual(
            calibrated["timing_admission"], "CALIBRATED_COMPONENT_ENVELOPE"
        )
        self.assertTrue(calibrated["fpga_component_envelope_calibrated"])
        self.assertEqual(calibrated["predicted_maintenance_cycles"], 30)
        self.assertEqual(calibrated["predicted_iterative_span_cycles"], 7)
        self.assertEqual(calibrated["calibrated_total_cycles"], 37)

    def test_zero_round_only_model_rejects_iterative_claim(self) -> None:
        zero_round_model = model(iterative=False)
        self.assertFalse(iterative_model_supported(zero_round_model))

        calibrated = calibrate_row(
            ledger_row(), raw_result(), zero_round_model
        )

        self.assertEqual(calibrated["timing_admission"], "STRUCTURE_ONLY")
        self.assertFalse(calibrated["fpga_component_envelope_calibrated"])
        self.assertIn("no nonzero iterative rounds", calibrated["timing_admission_reason"])

    def test_missing_ten_stage_timestamps_is_structure_only(self) -> None:
        row = ledger_row()
        row["ten_stage_supported"] = "False"
        row["ten_stage_ledger_closed"] = "False"

        calibrated = calibrate_row(row, raw_result(), model(iterative=True))

        self.assertEqual(calibrated["timing_admission"], "STRUCTURE_ONLY")
        self.assertFalse(calibrated["fpga_component_envelope_calibrated"])
        self.assertIn("direct timestamps", calibrated["timing_admission_reason"])

    def test_missing_vertices_is_structure_only(self) -> None:
        raw = raw_result()
        del raw["vertices"]

        calibrated = calibrate_row(ledger_row(), raw, model(iterative=True))

        self.assertEqual(calibrated["timing_admission"], "STRUCTURE_ONLY")
        self.assertIn("requires graph vertices", calibrated["timing_admission_reason"])

    def test_zero_round_ignores_preload_component_activity(self) -> None:
        raw = raw_result()
        raw["rounds"] = 0

        calibrated = calibrate_row(ledger_row(), raw, model(iterative=True))

        self.assertEqual(
            calibrated["timing_admission"], "CALIBRATED_COMPONENT_ENVELOPE"
        )
        self.assertEqual(calibrated["predicted_iterative_span_cycles"], 0)


if __name__ == "__main__":
    unittest.main()
