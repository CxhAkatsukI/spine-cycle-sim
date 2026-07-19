from __future__ import annotations

import unittest

from scripts.analyze_dstage_component_model import (
    base_whatif_replay_to_clipped,
    classify_status,
    correction_feature_values,
)


class DStageComponentModelTests(unittest.TestCase):
    def test_correction_features_map_to_hardware_actions(self) -> None:
        row = {
            "tile_clipped_ranges": 10,
            "tile_mixed_path": 1,
            "tile_max_clipped_ranges": 7,
            "tile_fallback_count": 3,
        }

        features = correction_feature_values(row)

        self.assertEqual(features["clipped_range_stream_correction"], 10.0)
        self.assertEqual(features["mixed_full_peak_range_correction"], 7.0)
        self.assertEqual(features["fallback_clipped_stream_correction"], 30.0)

    def test_status_thresholds_are_ordered(self) -> None:
        self.assertEqual(classify_status(10.0, 15.0, 30.0), "trusted")
        self.assertEqual(classify_status(20.0, 15.0, 30.0), "borderline")
        self.assertEqual(classify_status(31.0, 15.0, 30.0), "untrusted")

    def test_replay_whatif_does_not_increase_base_prediction(self) -> None:
        model = {
            "features": ["active_records_x_touched_tiles"],
            "means": {"active_records_x_touched_tiles": 0.0},
            "stds": {"active_records_x_touched_tiles": 1.0},
            "standardized_coefficients": {"active_records_x_touched_tiles": 2.0},
            "intercept": 10.0,
        }
        row = {
            "active_records_x_touched_tiles": 100,
            "tile_clipped_ranges": 25,
        }

        self.assertLess(base_whatif_replay_to_clipped(row, model), 210.0)


if __name__ == "__main__":
    unittest.main()
