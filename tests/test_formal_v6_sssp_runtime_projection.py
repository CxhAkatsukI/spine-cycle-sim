from __future__ import annotations

import importlib.util
from pathlib import Path
import json
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "project_formal_v6_sssp_runtime.py"
SPEC = importlib.util.spec_from_file_location("sssp_runtime_projection", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FormalV6SsspRuntimeProjectionTest(unittest.TestCase):
    def test_coefficient_is_median_of_admitted_work_rates(self) -> None:
        rows = [
            {"directed_records": 10, "supersteps": 2, "cycles": 200},
            {"directed_records": 10, "supersteps": 2, "cycles": 400},
            {"directed_records": 10, "supersteps": 2, "cycles": 300},
        ]
        self.assertEqual(MODULE.cycles_per_edge_round(rows), 15.0)

    def test_optimistic_projection_still_fails_closed(self) -> None:
        projection = MODULE.project_target(
            directed_records=1_000_000,
            supersteps=10,
            current_cycles=1_000_000,
            elapsed_seconds=100.0,
            coefficient=30.0,
            wall_budget_hours=0.1,
        )
        self.assertFalse(projection["wall_budget_feasible"])
        self.assertEqual(
            projection["recommended_action"],
            "soft_stop_and_classify_wall_time_infeasible",
        )

    def test_invalid_work_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.project_target(
                directed_records=0,
                supersteps=1,
                current_cycles=1,
                elapsed_seconds=1.0,
                coefficient=1.0,
                wall_budget_hours=1.0,
            )

    def test_preflight_projection_uses_nominal_rate_for_admission(self) -> None:
        projection = MODULE.project_preflight_target(
            directed_records=100_000,
            supersteps=10,
            coefficient=30.0,
            cycles_per_second=25_000.0,
            wall_budget_hours=1.0,
        )
        self.assertAlmostEqual(
            projection["projected_total_hours_at_calibration_rate"],
            1.0 / 3.0,
        )
        self.assertTrue(projection["wall_budget_feasible"])
        self.assertEqual(
            projection["recommended_action"], "launch_cycle_simulation"
        )

    def test_nominally_infeasible_preflight_is_not_rescued_by_stress_case(self) -> None:
        projection = MODULE.project_preflight_target(
            directed_records=20_000_000,
            supersteps=10,
            coefficient=30.0,
            cycles_per_second=25_000.0,
            wall_budget_hours=3.0,
        )
        self.assertGreater(
            projection["projected_total_hours_at_calibration_rate"], 3.0
        )
        self.assertFalse(projection["wall_budget_feasible"])
        self.assertEqual(
            projection["recommended_action"],
            "do_not_launch_wall_time_infeasible",
        )

    def test_one_round_screen_uses_minimum_algorithmic_work(self) -> None:
        projection = MODULE.project_one_round_target(
            directed_records=100_000_000,
            coefficient=30.0,
            cycles_per_second=30_000.0,
            wall_budget_hours=3.0,
        )
        self.assertEqual(projection["minimum_supersteps_used"], 1)
        self.assertEqual(projection["oracle_minimum_supersteps"], 1)
        self.assertAlmostEqual(
            projection["projected_total_hours_at_calibration_rate"],
            27.77777777777778,
        )
        self.assertFalse(projection["wall_budget_feasible"])
        self.assertIn("not_simulated_performance", projection["claim_class"])

    def test_historical_observation_survives_resume_state_reset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "events.jsonl").write_text(
                json.dumps(
                    {
                        "event": "job_finished",
                        "job_id": "job",
                        "elapsed_seconds": 12.5,
                        "peak_rss_bytes": 4096,
                    }
                )
                + "\n",
                encoding="ascii",
            )
            observation = MODULE.historical_job_observation(
                run_dir,
                {
                    "job_id": "job",
                    "elapsed_seconds": 0.0,
                    "peak_rss_bytes": 0,
                },
            )
        self.assertEqual(observation, (12.5, 4096))


if __name__ == "__main__":
    unittest.main()
