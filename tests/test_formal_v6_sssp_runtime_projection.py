from __future__ import annotations

import importlib.util
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
