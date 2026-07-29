from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.render_live_large_graph_report import (
    correctness_summary_rows,
    dataset_catalog_rows,
    headline_pair_rows,
    k4_update_sweep_rows,
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

    def test_k4_update_sweep_is_sorted_and_correctness_gated_upstream(self) -> None:
        base = {
            "dataset_id": "sx_askubuntu",
            "algorithm": "weighted_sssp",
            "competitor": "grasu_regraph_k4_shared",
            "spine_speedup": "4",
            "spine_update_speedup": "0.25",
            "competitor_memory_bytes": "30",
            "spine_memory_bytes": "10",
            "spine_energy_advantage": "2",
        }
        rows = k4_update_sweep_rows(
            [
                {**base, "scenario": "delete", "batch_size": "8"},
                {**base, "scenario": "insert", "batch_size": "64"},
                {**base, "scenario": "insert", "batch_size": "1"},
                {
                    **base,
                    "competitor": "grasu_regraph_k1",
                    "scenario": "insert",
                    "batch_size": "8",
                },
            ]
        )
        self.assertEqual([row["label"] for row in rows], ["Ins-1", "Ins-64", "Del-8"])
        self.assertEqual(rows[0]["memory_ratio"], 3.0)

    def test_correctness_summary_excludes_single_system_groups(self) -> None:
        rows = correctness_summary_rows(
            [
                {
                    "algorithm": "weighted_sssp",
                    "systems_present": "spine",
                    "final_state_exact_match": "True",
                    "complete_triplet": "False",
                    "final_state_match": "True",
                },
                {
                    "algorithm": "weighted_sssp",
                    "systems_present": "spine+grasu_regraph_k4_shared",
                    "final_state_exact_match": "True",
                    "complete_triplet": "False",
                    "final_state_match": "True",
                },
            ]
        )
        self.assertEqual(rows[0]["cross_system_groups"], 1)
        self.assertEqual(rows[0]["exact_groups"], 1)
        self.assertEqual(rows[0]["failed_groups"], 0)

    def test_dataset_catalog_uses_frozen_graph_views(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = root / "sx_askubuntu"
            dataset.mkdir()
            (dataset / "materialization_manifest.json").write_text(
                json.dumps(
                    {
                        "capacity": {
                            "vertices": 11,
                            "spine_full_graph_admitted": True,
                        },
                        "graphs": {
                            "directed": {"records": 12},
                            "reciprocal": {"records": 20},
                            "residual_sink_free": {"records": 15},
                        },
                    }
                ),
                encoding="utf-8",
            )
            rows = dataset_catalog_rows(root)
        self.assertEqual(rows[0]["vertices"], 11)
        self.assertEqual(rows[0]["cc_edges"], 20)


if __name__ == "__main__":
    unittest.main()
