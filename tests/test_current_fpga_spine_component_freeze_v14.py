import unittest

from scripts.freeze_current_fpga_spine_component_features_v14 import (
    component_active_cycles,
    component_feature_record,
    component_request_count,
)


class CurrentFPGASpineComponentFreezeV14Tests(unittest.TestCase):
    def test_component_active_cycles_prefers_explicit_counter(self):
        result = {
            "reader_active_cycles_per_round": [7, 11],
            "reader_start_cycles_per_round": [10],
            "reader_end_cycles_per_round": [999],
        }
        self.assertEqual(component_active_cycles(result, "reader"), 18)

    def test_component_active_cycles_falls_back_to_intervals(self):
        result = {
            "compute_start_cycles_per_round": [10, 40],
            "compute_end_cycles_per_round": [31, 53],
        }
        self.assertEqual(component_active_cycles(result, "compute"), 34)

    def test_component_request_count_checks_completion(self):
        result = {
            "reader_memory_requests_issued_per_round": [3, 5],
            "reader_memory_requests_completed_per_round": [3, 5],
        }
        self.assertEqual(component_request_count(result, "reader"), 8)
        result["reader_memory_requests_completed_per_round"] = [3, 4]
        with self.assertRaisesRegex(ValueError, "ledger is open"):
            component_request_count(result, "reader")

    def test_parent_request_fallback_checks_completion(self):
        result = {
            "compute_component_parent_requests_issued": 17,
            "compute_component_parent_requests_completed": 17,
        }
        self.assertEqual(component_request_count(result, "compute"), 17)

    def test_zero_round_record_rejects_hidden_work(self):
        result = {
            "iterations": 0,
            "maintenance_cycles": 100,
            "reader_start_cycles_per_round": [0],
            "reader_end_cycles_per_round": [1],
            "compute_start_cycles_per_round": [],
            "compute_end_cycles_per_round": [],
        }
        hardware = [
            {
                "maintenance_kernel_ms": "1",
                "reader_ms": "0",
                "compute_ms": "0",
                "kernel_span_ms": "0",
            }
        ]
        with self.assertRaisesRegex(ValueError, "zero-round"):
            component_feature_record(
                algorithm="thresholded_residual_pagerank",
                profile_id="p",
                dataset="d",
                role="calibration",
                result=result,
                hardware=hardware,
                clock_mhz=1,
            )


if __name__ == "__main__":
    unittest.main()
