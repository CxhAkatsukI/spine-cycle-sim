from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.render_formal_v6_primary import (
    admitted_pairs,
    behavior_transition_tex,
    publication_dataset_scope,
    wall_time_feasibility_tex,
)


class FormalV6ReportTests(unittest.TestCase):
    def test_behavior_transition_lists_only_invalidated_rows(self) -> None:
        text = behavior_transition_tex(
            [
                {
                    "dataset_id": "soc_pokec",
                    "algorithm": "weighted_sssp",
                    "coverage_status": "invalidated_by_behavior_transition",
                },
                {
                    "dataset_id": "sx_stackoverflow",
                    "algorithm": "connected_components",
                    "coverage_status": "observed_pass",
                },
            ]
        )
        self.assertIn("following 1 prior Spine rows", text)
        self.assertIn("PK-SSSP", text)
        self.assertNotIn("SO-CC", text)

    def test_wall_time_projection_is_explicitly_not_performance(self) -> None:
        text = wall_time_feasibility_tex(
            {
                "calibration_rows": [{}, {}, {}],
                "targets": [
                    {
                        "dataset_id": "sx_stackoverflow",
                        "projected_total_hours_at_observed_rate": 105.7,
                        "optimistic_remaining_hours_10x_less_work_2x_rate": 3.57,
                        "wall_budget_hours": 3.0,
                    },
                    {
                        "dataset_id": "soc_pokec",
                        "projected_total_hours_at_observed_rate": 342.2,
                        "optimistic_remaining_hours_10x_less_work_2x_rate": 16.76,
                        "wall_budget_hours": 3.0,
                    },
                ],
                "preflight_targets": [
                    {
                        "dataset_id": "rmat_19_32",
                        "directed_records": 15_483_485,
                        "oracle_minimum_supersteps": 10,
                        "projected_total_hours_at_calibration_rate": 52.8,
                    }
                ],
            }
        )
        self.assertIn("SO 105.7 h", text)
        self.assertIn("PK 342.2 h", text)
        self.assertIn("soft-stopped by policy", text)
        self.assertIn("never enter accelerator-performance", text)
        self.assertIn("R19 preflight requires 10 supersteps", text)
        self.assertIn("52.8 h", text)

    def test_wall_time_projection_requires_targets(self) -> None:
        with self.assertRaises(ValueError):
            wall_time_feasibility_tex({"calibration_rows": [], "targets": []})

    def test_r19_pair_is_retained_as_separate_endpoint(self) -> None:
        row = {
            "competitor": "grasu_regraph_k4_shared",
            "scenario": "insert",
            "batch_size": "8",
            "algorithm": "weighted_sssp",
            "dataset_id": "rmat_19_32",
            "spine_cycles": "100",
            "competitor_cycles": "250",
            "spine_speedup": "2.5",
            "spine_host_wall_seconds": "1.0",
            "competitor_host_wall_seconds": "2.0",
            "spine_memory_bytes": "64",
            "competitor_memory_bytes": "128",
            "spine_random_request_fraction": "0.5",
            "competitor_random_request_fraction": "0.25",
            "spine_dram_energy_pj": "10",
            "competitor_dram_energy_pj": "20",
        }
        pairs = admitted_pairs([row])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["dataset"], "R19")
        self.assertEqual(pairs[0]["label"], "R19-SSSP")

    def test_dataset_scope_is_derived_from_materialization_capacity(self) -> None:
        contract = {
            "datasets": [
                {"dataset_id": "small", "abbreviation": "SM"},
                {"dataset_id": "large", "abbreviation": "LG"},
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for dataset_id, vertices, admitted in (
                ("small", 10, True),
                ("large", 200, False),
            ):
                directory = root / dataset_id
                directory.mkdir()
                (directory / "materialization_manifest.json").write_text(
                    json.dumps(
                        {
                            "dataset_id": dataset_id,
                            "capacity": {
                                "vertices": vertices,
                                "spine_max_vertices": 128,
                                "spine_full_graph_admitted": admitted,
                            },
                        }
                    ),
                    encoding="ascii",
                )
            scope = publication_dataset_scope(contract, root)

        self.assertEqual(scope["catalog_datasets"], 2)
        self.assertEqual(scope["admitted_datasets"], 1)
        self.assertEqual(scope["spine_max_vertices"], 128)
        self.assertFalse(scope["rows"][1]["spine_full_graph_admitted"])


if __name__ == "__main__":
    unittest.main()
