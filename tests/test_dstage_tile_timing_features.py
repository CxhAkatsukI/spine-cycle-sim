from __future__ import annotations

import unittest

from scripts.analyze_hw_dstage_tile_timing import merge_features


class DStageTileTimingFeatureTests(unittest.TestCase):
    def test_merge_features_adds_partition_and_full_replay_terms(self) -> None:
        summary_rows = [
            {
                "case": "case",
                "successful_repeats": "3",
                "repeats": "3",
                "median_conv_span_ms": "1.0",
                "median_active_records": "4",
            }
        ]
        tile_rows = [
            {
                "case": "case",
                "repeat": "1",
                "partition": "0",
                "path": "full",
                "tile_work": "4097",
                "clipped_ranges": "4",
                "swept_vertex_words": "8192",
                "gathered_vertex_words": "0",
                "scattered_vertex_words": "0",
            },
            {
                "case": "case",
                "repeat": "1",
                "partition": "2",
                "path": "fast",
                "tile_work": "16",
                "clipped_ranges": "4",
                "swept_vertex_words": "0",
                "gathered_vertex_words": "16",
                "scattered_vertex_words": "16",
            },
        ]

        row = merge_features(summary_rows, tile_rows)[0]

        self.assertEqual(row["tile_partition_count"], 2.0)
        self.assertEqual(row["tile_multi_partition"], 1.0)
        self.assertEqual(row["tile_max_partition_work"], 4097.0)
        self.assertEqual(row["active_records_x_touched_tiles"], 8.0)
        self.assertEqual(row["fast_records_x_tiles"], 4.0)
        self.assertEqual(row["full_records_x_tiles"], 4.0)
        self.assertEqual(row["partition_count_x_active_records"], 8.0)
        self.assertAlmostEqual(row["full_work_per_active_record"], 1024.25)
        self.assertEqual(row["full_work_per_full_tile"], 4097.0)


if __name__ == "__main__":
    unittest.main()
