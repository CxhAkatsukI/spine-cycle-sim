import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "analyze_current_fpga_spine_mechanism_components_v15",
    ROOT / "scripts/analyze_current_fpga_spine_mechanism_components_v15.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SpineMechanismComponentsV15AnalysisTest(unittest.TestCase):
    def test_subsystem_status_is_independent_of_timing_admission(self) -> None:
        self.assertEqual(
            MODULE.row_validation_status([{"status": "PASS"}], missing=[]),
            "PASS",
        )
        self.assertEqual(
            MODULE.row_validation_status([{"status": "FAIL"}], missing=[]),
            "FAIL",
        )
        self.assertEqual(
            MODULE.row_validation_status([{"status": "PASS"}], missing=["case"]),
            "INCOMPLETE",
        )

    def test_timing_failures_name_rank_and_component_gates(self) -> None:
        contract = {
            "thresholds": {
                "holdout_total_median_absolute_error_percent_max": 15.0,
                "holdout_total_absolute_error_percent_max": 30.0,
                "holdout_component_median_absolute_error_percent_max": 20.0,
                "holdout_component_absolute_error_percent_max": 40.0,
                "workload_rank_spearman_min": 0.9,
            }
        }
        failures = MODULE.timing_gate_failures(
            contract,
            [
                {
                    "algorithm": "connected_components",
                    "median_absolute_error_percent": 6.7,
                    "max_absolute_error_percent": 12.6,
                    "workload_rank_spearman": -1.0,
                }
            ],
            [
                {
                    "algorithm": "connected_components",
                    "component": "compute",
                    "median_absolute_error_percent": 37.4,
                    "max_absolute_error_percent": 37.7,
                }
            ],
        )
        self.assertEqual(
            [(row["gate"], row["scope"]) for row in failures],
            [
                ("workload_rank_spearman", "total"),
                ("component_median_absolute_error_percent", "component"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
