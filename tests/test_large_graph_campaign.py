from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from spine_cycle_sim.experiments import (
    LARGE_GRAPH_REQUIRED_ALGORITHMS,
    LARGE_GRAPH_REQUIRED_DATASET_IDS,
    LARGE_GRAPH_REQUIRED_SYSTEMS,
    load_large_graph_campaign_contract,
    planned_system_runs,
    validate_large_graph_campaign_contract,
    verify_large_graph_sources,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT / "configs" / "contracts" / "large_graph_publication_campaign_v1.json"
)
DATASET_ROOT = Path("/data/feiyang/Graph_Datasets")


class LargeGraphCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_large_graph_campaign_contract(CONTRACT)

    def test_frozen_dataset_algorithm_and_system_sets(self) -> None:
        self.assertEqual(
            tuple(dataset["dataset_id"] for dataset in self.contract["datasets"]),
            LARGE_GRAPH_REQUIRED_DATASET_IDS,
        )
        self.assertEqual(
            tuple(self.contract["experiment_matrix"]["main_e2e"]["algorithms"]),
            LARGE_GRAPH_REQUIRED_ALGORITHMS,
        )
        self.assertEqual(
            tuple(self.contract["experiment_matrix"]["systems"]),
            LARGE_GRAPH_REQUIRED_SYSTEMS,
        )

    def test_full_pagerank_and_residual_semantics_are_frozen(self) -> None:
        semantics = self.contract["workload_semantics"]
        self.assertEqual(semantics["full_pagerank"]["edge_cap"], 4_000_000)
        self.assertEqual(
            semantics["full_pagerank"]["scaling_edges"],
            [64_000, 256_000, 1_000_000, 4_000_000],
        )
        self.assertEqual(
            semantics["thresholded_residual_pagerank"]["per_vertex_threshold"],
            1.0e-6,
        )
        self.assertEqual(
            semantics["thresholded_residual_pagerank"]["threshold_semantics"],
            "abs_residual_per_vertex_gt_threshold",
        )

    def test_matrix_counts_make_campaign_cost_explicit(self) -> None:
        counts = planned_system_runs(self.contract)
        self.assertEqual(counts["main_e2e"], 132)
        self.assertEqual(counts["update_performance"], 297)
        self.assertEqual(counts["update_triggered_compute"], 180)
        self.assertEqual(counts["dense"], 108)
        self.assertEqual(counts["mixed_supplement"], 60)

    def test_every_source_is_present_with_expected_size(self) -> None:
        rows = verify_large_graph_sources(self.contract, DATASET_ROOT)
        self.assertEqual(len(rows), 11)
        self.assertTrue(all(row.status == "ok" for row in rows), rows)

    def test_correctness_contract_cannot_be_weakened(self) -> None:
        weakened = deepcopy(self.contract)
        weakened["correctness_admission"]["independent_mathematical_oracle"] = False
        with self.assertRaisesRegex(ValueError, "correctness admission"):
            validate_large_graph_campaign_contract(weakened)

    def test_automatic_timeout_and_compact_ids_are_rejected(self) -> None:
        timed = deepcopy(self.contract)
        timed["execution"]["automatic_timeout_seconds"] = 3600
        with self.assertRaisesRegex(ValueError, "soft-stop"):
            validate_large_graph_campaign_contract(timed)
        compact = deepcopy(self.contract)
        compact["workload_semantics"]["preserve_external_vertex_ids"] = False
        with self.assertRaisesRegex(ValueError, "external vertex IDs"):
            validate_large_graph_campaign_contract(compact)


if __name__ == "__main__":
    unittest.main()
