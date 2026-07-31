from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.render_formal_v6_primary import (
    admitted_pairs,
    all_spine_e2e_rows,
    behavior_transition_tex,
    publication_dataset_scope,
    wall_time_feasibility_tex,
)


class FormalV6ReportTests(unittest.TestCase):
    def test_all_spine_rows_keep_unpaired_results_and_classify_evidence(self) -> None:
        system_rows = [
            {
                "system": "spine",
                "scenario": "insert",
                "batch_size": "8",
                "algorithm": "weighted_sssp",
                "dataset_id": dataset_id,
                "dataset_kind": "real",
                "cycles": cycles,
            }
            for dataset_id, cycles in (
                ("sx_askubuntu", "100"),
                ("sx_stackoverflow", "200"),
                ("soc_livejournal1", "300"),
                ("rmat_19_32", "400"),
            )
        ]
        pairs = [
            {
                "dataset_id": "sx_askubuntu",
                "algorithm": "weighted_sssp",
                "k4_cycles": 500,
            }
        ]
        projection = {
            "targets": [
                {
                    "dataset_id": "sx_stackoverflow",
                    "projected_cycles": 2_000,
                    "current_cycles": 250,
                    "projected_total_hours_at_observed_rate": 100.0,
                }
            ],
            "preflight_targets": [
                {
                    "dataset_id": "rmat_19_32",
                    "projected_cycles": 4_000,
                    "projected_total_hours_at_calibration_rate": 50.0,
                }
            ],
            "one_round_screen_targets": [
                {
                    "dataset_id": "soc_livejournal1",
                    "projected_cycles": 3_000,
                    "projected_total_hours_at_calibration_rate": 25.0,
                }
            ],
        }

        rows = all_spine_e2e_rows(
            system_rows,
            pairs,
            projection,
            {
                "lower_bounds": [
                    {
                        "dataset_id": "sx_stackoverflow",
                        "algorithm": "connected_components",
                        "spine_cycles": 250,
                        "observed_partial_cycles": 1_500,
                        "claim_class": "strict_lower_bound",
                    }
                ]
            },
        )
        by_dataset = {row["dataset_id"]: row for row in rows}

        self.assertEqual(len(rows), 4)
        self.assertEqual(by_dataset["sx_askubuntu"]["k4_status"], "measured")
        self.assertEqual(
            by_dataset["sx_stackoverflow"]["k4_status"],
            "timeout_projected",
        )
        self.assertEqual(
            by_dataset["soc_livejournal1"]["k4_status"],
            "timeout_one_round_screen",
        )
        self.assertEqual(
            by_dataset["rmat_19_32"]["evidence_kind"],
            "validated_preflight_projection",
        )
        self.assertEqual(
            by_dataset["sx_stackoverflow"]["observed_partial_cycles"], 250
        )

    def test_stopped_prefix_is_not_promoted_to_measured_or_projected(self) -> None:
        rows = all_spine_e2e_rows(
            [
                {
                    "execution_id": "spine-cc",
                    "system": "spine",
                    "scenario": "insert",
                    "batch_size": "8",
                    "algorithm": "connected_components",
                    "dataset_id": "sx_stackoverflow",
                    "dataset_kind": "real",
                    "cycles": "100",
                }
            ],
            [],
            {},
            {
                "lower_bounds": [
                    {
                        "dataset_id": "sx_stackoverflow",
                        "algorithm": "connected_components",
                        "spine_cycles": 100,
                        "observed_partial_cycles": 550,
                        "claim_class": "strict_lower_bound",
                    }
                ]
            },
        )
        self.assertEqual(rows[0]["k4_status"], "timeout_strict_lower_bound")
        self.assertEqual(rows[0]["k4_cycles"], 550)
        self.assertEqual(rows[0]["implied_speedup"], 5.5)

    def test_unpaired_sssp_requires_explicit_feasibility_evidence(self) -> None:
        with self.assertRaises(ValueError):
            all_spine_e2e_rows(
                [
                    {
                        "system": "spine",
                        "scenario": "insert",
                        "batch_size": "8",
                        "algorithm": "weighted_sssp",
                        "dataset_id": "soc_pokec",
                        "cycles": "100",
                    }
                ],
                [],
                {},
            )

    def test_v3_preflight_projection_requires_matching_spine_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "source differs"):
            all_spine_e2e_rows(
                [
                    {
                        "system": "spine",
                        "scenario": "insert",
                        "batch_size": "8",
                        "algorithm": "weighted_sssp",
                        "dataset_id": "soc_livejournal1",
                        "cycles": "100",
                        "source_external": "71",
                        "source_cohort": "median_degree",
                    }
                ],
                [],
                {
                    "schema_version": 3,
                    "preflight_targets": [
                        {
                            "dataset_id": "soc_livejournal1",
                            "preflight_source_external": 72,
                            "preflight_source_cohort": "median_degree",
                            "projected_cycles": 1_000,
                            "projected_total_hours_at_calibration_rate": 1.0,
                        }
                    ],
                },
            )

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
                        "preflight_source_external": 113,
                        "projected_total_hours_at_calibration_rate": 52.8,
                    }
                ],
                "one_round_screen_targets": [
                    {
                        "dataset_id": "soc_livejournal1",
                        "projected_total_hours_at_calibration_rate": 27.1,
                    },
                    {
                        "dataset_id": "soc_orkut",
                        "projected_total_hours_at_calibration_rate": 74.2,
                    },
                ],
            }
        )
        self.assertIn("SO 105.7 h", text)
        self.assertIn("PK 342.2 h", text)
        self.assertIn("soft-stopped by policy", text)
        self.assertIn("never enter accelerator-performance", text)
        self.assertIn("R19 source", text)
        self.assertIn("10 supersteps", text)
        self.assertIn("52.8 h", text)
        self.assertIn("remaining 2 unlaunched real graphs", text)
        self.assertIn("LJ 27.1 h", text)
        self.assertIn("OK 74.2 h", text)
        self.assertIn("not performance data", text)

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
