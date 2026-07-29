from __future__ import annotations

import unittest

from scripts.render_live_large_graph_report import (
    headline_pair_rows,
    render_tex,
    runtime_summary,
)


class LiveLargeGraphReportTests(unittest.TestCase):
    def test_headline_pairs_keep_k1_and_k4_separate(self) -> None:
        base = {
            "group_id": "group",
            "dataset_id": "sx_askubuntu",
            "algorithm": "connected_components",
            "scenario": "insert",
            "batch_size": "8",
            "spine_memory_bytes": "10",
            "spine_update_speedup": "0.25",
            "spine_energy_advantage": "3",
        }
        rows = headline_pair_rows(
            [
                {
                    **base,
                    "competitor": "grasu_regraph_k1",
                    "spine_speedup": "4",
                    "competitor_memory_bytes": "50",
                },
                {
                    **base,
                    "competitor": "grasu_regraph_k4_shared",
                    "spine_speedup": "2",
                    "competitor_memory_bytes": "30",
                },
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["k1_speedup"], 4.0)
        self.assertEqual(rows[0]["k4_speedup"], 2.0)
        self.assertEqual(rows[0]["k1_memory_ratio"], 5.0)
        self.assertEqual(rows[0]["k4_memory_ratio"], 3.0)

    def test_non_headline_batch_is_excluded(self) -> None:
        self.assertEqual(
            headline_pair_rows(
                [
                    {
                        "dataset_id": "sx_askubuntu",
                        "algorithm": "connected_components",
                        "scenario": "insert",
                        "batch_size": "64",
                    }
                ]
            ),
            [],
        )

    def test_runtime_summary_does_not_enter_speedup_math(self) -> None:
        summary = runtime_summary(
            [
                {
                    "scenario": "insert",
                    "batch_size": "8",
                    "system": "spine",
                    "host_wall_seconds": "1",
                },
                {
                    "scenario": "insert",
                    "batch_size": "8",
                    "system": "spine",
                    "host_wall_seconds": "9",
                },
            ]
        )
        self.assertEqual(summary[0]["median_seconds"], 5.0)
        self.assertEqual(summary[0]["max_seconds"], 9.0)

    def test_reference_line_uses_observed_pair_extent(self) -> None:
        tex = render_tex(
            summary={
                "status": "PARTIAL",
                "observed_executions": 3,
                "expected_executions": 9,
                "complete_triplets": 1,
            },
            runtime=[],
            pair_count=5,
        )
        self.assertIn("coordinates {(0,1) (4,1)}", tex)
        self.assertNotIn("coordinates {(0,1) (20,1)}", tex)


if __name__ == "__main__":
    unittest.main()
