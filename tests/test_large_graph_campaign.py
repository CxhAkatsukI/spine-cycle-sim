from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from spine_cycle_sim.experiments import (
    LARGE_GRAPH_REQUIRED_ALGORITHMS,
    LARGE_GRAPH_REQUIRED_DATASET_IDS,
    LARGE_GRAPH_REQUIRED_SYSTEMS,
    build_materialization_campaign_manifest,
    load_large_graph_campaign_contract,
    planned_system_runs,
    validate_large_graph_campaign_contract,
    verify_large_graph_sources,
)
from spine_cycle_sim.experiments.campaign_runtime import validate_campaign_manifest


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
        self.assertEqual(
            semantics["thresholded_residual_pagerank"]["execution_contract"],
            "deltahls_sink_free_linf_warm",
        )
        self.assertEqual(
            semantics["thresholded_residual_pagerank"]["graph_projection"],
            "add_self_loop_to_each_zero_outdegree_vertex_v1",
        )
        self.assertEqual(
            semantics["full_pagerank"]["slice_policy"],
            "exact_min_edge_hash_preserving_original_vertex_ids_v2",
        )
        endpoint = self.contract["synthetic_endpoint"]
        self.assertEqual(endpoint["materialized_source_records"], 15_483_988)
        self.assertEqual(endpoint["self_loops_removed"], 503)
        self.assertEqual(endpoint["expected_unique_directed_edges"], 15_483_485)
        self.assertEqual(
            endpoint["source"]["sha256"],
            "00a8886a5d0836e2839d50401142056f76cccd854845701b7a6100ca6db31125",
        )

    def test_matrix_counts_make_campaign_cost_explicit(self) -> None:
        counts = planned_system_runs(self.contract)
        self.assertEqual(counts["main_e2e"], 132)
        self.assertEqual(counts["update_performance"], 297)
        self.assertEqual(counts["update_triggered_compute"], 180)
        self.assertEqual(counts["dense"], 108)
        self.assertEqual(counts["mixed_supplement"], 60)

    def test_materialization_manifest_covers_all_sources(self) -> None:
        manifest = build_materialization_campaign_manifest(
            self.contract,
            output_root=Path("/tmp/publication-materialization-test"),
            python="python3",
        )
        validate_campaign_manifest(manifest)
        self.assertEqual(len(manifest["jobs"]), 11)
        self.assertEqual(
            [job["dataset_id"] for job in manifest["jobs"]],
            list(LARGE_GRAPH_REQUIRED_DATASET_IDS),
        )
        self.assertTrue(
            all("--out-dir" in job["command"] for job in manifest["jobs"])
        )

    def test_every_source_is_present_with_expected_size(self) -> None:
        rows = verify_large_graph_sources(self.contract, DATASET_ROOT)
        self.assertEqual(len(rows), 11)
        self.assertTrue(all(row.status == "ok" for row in rows), rows)

    def test_reviewed_dynamic_acts_archive_members_and_projections(self) -> None:
        datasets = {
            dataset["dataset_id"]: dataset for dataset in self.contract["datasets"]
        }
        livejournal = datasets["soc_livejournal1"]["source"]
        self.assertEqual(livejournal["encoding"], "tar_matrix_market")
        self.assertEqual(
            livejournal["archive_member"],
            "soc-LiveJournal1/soc-LiveJournal1.mtx",
        )
        self.assertEqual(
            datasets["soc_orkut"]["source"]["archive_member"],
            "com-Orkut/com-Orkut.mtx",
        )
        for dataset_id in ("soc_pokec", "soc_orkut", "soc_livejournal1", "ljournal_2008"):
            self.assertEqual(
                datasets[dataset_id]["source"]["semantic_projection"],
                "reciprocal_to_paper_edge_count",
            )

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
