from __future__ import annotations

from copy import deepcopy
from collections import Counter
import hashlib
from pathlib import Path
import unittest

from spine_cycle_sim.experiments import (
    LARGE_GRAPH_REQUIRED_ALGORITHMS,
    LARGE_GRAPH_REQUIRED_DATASET_IDS,
    LARGE_GRAPH_REQUIRED_SYSTEMS,
    build_materialization_campaign_manifest,
    build_publication_experiment_campaign_manifest,
    grasu_profile_hbm_admission,
    load_large_graph_campaign_contract,
    planned_system_runs,
    publication_case_requests,
    spine_profile_vertex_admitted,
    validate_large_graph_campaign_contract,
    verify_large_graph_sources,
)
from spine_cycle_sim.experiments.campaign_runtime import validate_campaign_manifest
from spine_cycle_sim.experiments.large_graph_campaign import (
    _publication_job_priority,
    _publication_rss_gib,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT / "configs" / "contracts" / "large_graph_publication_campaign_v1.json"
)
FULLGRAPH_CONTRACT = (
    ROOT
    / "configs"
    / "contracts"
    / "large_graph_publication_campaign_fullgraph_v2.json"
)
FULLGRAPH_V4_CONTRACT = (
    ROOT
    / "configs"
    / "contracts"
    / "large_graph_publication_campaign_fullgraph_v4.json"
)
FULLGRAPH_V5_CONTRACT = (
    ROOT
    / "configs"
    / "contracts"
    / "large_graph_publication_campaign_fullgraph_v5.json"
)
FULLGRAPH_V6_CONTRACT = (
    ROOT
    / "configs"
    / "contracts"
    / "large_graph_publication_campaign_fullgraph_v6.json"
)
FULLGRAPH_V7_CONTRACT = (
    ROOT
    / "configs"
    / "contracts"
    / "large_graph_publication_campaign_fullgraph_v7.json"
)
DATASET_ROOT = Path("/data/feiyang/Graph_Datasets")


class LargeGraphCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_large_graph_campaign_contract(CONTRACT)

    def test_publication_rss_estimate_covers_observed_grasu_pma_overhead(self) -> None:
        grasu_full_pr = _publication_rss_gib(
            3_072_441, 4_000_000, "grasu_regraph_k4_shared"
        )
        spine_full_pr = _publication_rss_gib(3_072_441, 4_000_000, "spine")
        self.assertGreaterEqual(grasu_full_pr, 13.4)
        self.assertGreater(grasu_full_pr, spine_full_pr)
        self.assertEqual(
            _publication_rss_gib(
                524_288, 29_732_038, "grasu_regraph_k1"
            ),
            64.0,
        )

    def test_grasu_row_lower_bound_excludes_only_proven_hbm_overflow(self) -> None:
        contract = load_large_graph_campaign_contract(FULLGRAPH_CONTRACT)
        bitcoin = grasu_profile_hbm_admission(
            contract,
            repository_root=ROOT,
            system="grasu_regraph_k4_shared",
            algorithm="weighted_sssp",
            vertices=24_575_382,
        )
        pokec = grasu_profile_hbm_admission(
            contract,
            repository_root=ROOT,
            system="grasu_regraph_k4_shared",
            algorithm="weighted_sssp",
            vertices=1_632_803,
        )
        self.assertFalse(bitcoin["row_lower_bound_fits"])
        self.assertGreater(
            bitcoin["row_storage_lower_bound_bytes"],
            bitcoin["hbm_capacity_bytes"],
        )
        self.assertTrue(pokec["row_lower_bound_fits"])

    def test_fullgraph_v4_freezes_spine_host_runtime_equivalence(self) -> None:
        contract = load_large_graph_campaign_contract(FULLGRAPH_V4_CONTRACT)
        simulator = contract["architecture_baselines"]["simulator_baseline"]
        equivalents = simulator["spine_host_runtime_equivalent_plugins"]
        self.assertEqual(len(equivalents), 1)
        self.assertEqual(
            equivalents[0]["baseline_plugin_sha256"],
            simulator["plugin_sha256"],
        )
        self.assertEqual(len(equivalents[0]["evidence_reports"]), 2)

    def test_fullgraph_v5_freezes_hot_partition_clip_transition(self) -> None:
        previous = load_large_graph_campaign_contract(FULLGRAPH_V4_CONTRACT)
        contract = load_large_graph_campaign_contract(FULLGRAPH_V5_CONTRACT)
        simulator = contract["architecture_baselines"]["simulator_baseline"]
        self.assertEqual(
            simulator["plugin_sha256"],
            "5c0211c60431bba211758dcb9031e906871eaae844172bfd6f3533a1c2a74f2d",
        )
        self.assertEqual(
            simulator["source_commit"],
            "918e08464f30cfd102e53f729d8559a9ea9923fc",
        )
        self.assertEqual(simulator["spine_host_runtime_equivalent_plugins"], [])
        supersedence = simulator["result_supersedence"]
        self.assertEqual(
            supersedence["superseding_plugin_sha256"],
            simulator["plugin_sha256"],
        )
        self.assertEqual(supersedence["classification"], "hls_behavior_correction")
        self.assertEqual(supersedence["affected_metric"], "resident_hot_edges")
        self.assertEqual(supersedence["affected_when_greater_than"], 0)
        self.assertEqual(len(supersedence["superseded_plugin_sha256"]), 2)
        self.assertEqual(
            simulator["hls_reference"]["revision"],
            "2655b24b3aed498467e07967e668a5ce4c63dea9",
        )
        self.assertEqual(
            contract["experiment_matrix"], previous["experiment_matrix"]
        )
        self.assertEqual(contract["datasets"], previous["datasets"])

    def test_fullgraph_v6_freezes_warm_sssp_measurement(self) -> None:
        contract = load_large_graph_campaign_contract(FULLGRAPH_V6_CONTRACT)
        simulator = contract["architecture_baselines"]["simulator_baseline"]
        self.assertEqual(
            simulator["plugin_sha256"],
            "96b4375f8549016ac8be36d85b04b4b5730df0af477dcc5909903845a8f56919",
        )
        self.assertEqual(
            simulator["source_commit"],
            "957f29420f4c4a513794d01c0a373dcb10c21a6f",
        )
        self.assertEqual(
            simulator["measurement_window"]["positive_weighted_sssp"],
            "untimed_verified_old_graph_state_then_timed_update_to_convergence",
        )
        weighted = contract["workload_semantics"]["weighted_sssp"]
        self.assertEqual(weighted["primary_source_cohort"], "median_degree")
        self.assertEqual(
            weighted["source_cohort_roles"]["high_degree"], "stress_only"
        )
        self.assertEqual(
            weighted["positive_insertion_measurement_window"],
            "dynamic_e2e_to_convergence",
        )
        self.assertEqual(
            contract["claim_boundary"]["weighted_sssp_bootstrap"],
            "reported_separately_and_excluded_from_dynamic_e2e",
        )

    def test_fullgraph_v7_freezes_device_active_timing(self) -> None:
        previous = load_large_graph_campaign_contract(FULLGRAPH_V6_CONTRACT)
        contract = load_large_graph_campaign_contract(FULLGRAPH_V7_CONTRACT)
        simulator = contract["architecture_baselines"]["simulator_baseline"]
        self.assertEqual(
            simulator["plugin_sha256"],
            "84626d7f2de2904df2557c9e08299495b28e7cd5389e075dc094550f75965216",
        )
        self.assertEqual(
            simulator["source_commit"],
            "af32f08d733577ebc20939e4321389dbf6695191",
        )
        self.assertEqual(
            simulator["behavior_transition"],
            "device_active_frontier_and_dynamic_sssp_e2e_window",
        )
        self.assertEqual(
            simulator["measurement_window"]["positive_weighted_sssp"],
            "untimed_verified_old_graph_state_then_timed_update_to_convergence",
        )
        self.assertEqual(
            simulator["hls_reference"],
            {
                "branch": "codex/skip-fit-hot-promotion",
                "revision": "867bee49e483950a82d69d3f3d8b0661ccbef544",
                "symbol": "partitioned_classify_hot_cold_from_indegree",
            },
        )
        supersedence = simulator["result_supersedence"]
        self.assertEqual(
            supersedence["classification"], "device_active_timing_correction"
        )
        self.assertEqual(
            supersedence["affected_algorithms"],
            [
                "connected_components",
                "thresholded_residual_pagerank",
                "weighted_sssp",
                "weighted_dynamic_sssp",
            ],
        )
        self.assertEqual(
            supersedence["superseding_plugin_sha256"],
            simulator["plugin_sha256"],
        )
        self.assertIn(
            previous["architecture_baselines"]["simulator_baseline"][
                "plugin_sha256"
            ],
            supersedence["superseded_plugin_sha256"],
        )
        self.assertEqual(contract["experiment_matrix"], previous["experiment_matrix"])
        self.assertEqual(contract["datasets"], previous["datasets"])

    def test_publication_launches_k4_before_k1_for_the_same_workload(self) -> None:
        priorities = {
            system: _publication_job_priority(
                base_priority=100,
                records=15_000_000,
                system=system,
            )
            for system in LARGE_GRAPH_REQUIRED_SYSTEMS
        }
        self.assertLess(priorities["spine"], priorities["grasu_regraph_k4_shared"])
        self.assertLess(
            priorities["grasu_regraph_k4_shared"],
            priorities["grasu_regraph_k1"],
        )

    def test_publication_system_order_does_not_invert_workload_priority(self) -> None:
        earlier_k1 = _publication_job_priority(
            base_priority=0,
            records=8_000_000,
            system="grasu_regraph_k1",
        )
        later_spine = _publication_job_priority(
            base_priority=0,
            records=9_000_000,
            system="spine",
        )
        self.assertLess(earlier_k1, later_spine)

    def test_publication_priority_rejects_an_unknown_system(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown publication system"):
            _publication_job_priority(
                base_priority=0,
                records=1,
                system="unknown",
            )

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

    def test_fullgraph_contract_freezes_v7_profiles_and_23pc_mapper(self) -> None:
        contract = load_large_graph_campaign_contract(FULLGRAPH_CONTRACT)
        baselines = contract["architecture_baselines"]
        self.assertEqual(
            baselines["grasu_regraph_capability_catalog"]["path"],
            "configs/contracts/grasu_regraph_full_graph_capabilities_v7.json",
        )
        for system in ("grasu_regraph_k1", "grasu_regraph_k4_shared"):
            baseline = baselines[system]
            self.assertEqual(
                baseline["addressing"],
                "runtime_packed_interleaved_v2_23pc_capacity_checked",
            )
            for profile_path, expected_hash in baseline["profiles"].values():
                path = ROOT / profile_path
                self.assertTrue(path.is_file())
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(), expected_hash
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
        self.assertEqual(counts["endpoint_scalability"], 12)
        self.assertEqual(counts["update_performance"], 297)
        self.assertEqual(counts["update_triggered_compute"], 180)
        self.assertEqual(counts["dense"], 108)
        self.assertEqual(counts["mixed_supplement"], 60)

    def test_logical_case_requests_match_every_frozen_tier(self) -> None:
        requests = publication_case_requests(self.contract)
        by_tier = Counter(request.tier for request in requests)
        self.assertEqual(len(requests), 789)
        self.assertEqual(by_tier, planned_system_runs(self.contract))
        update_algorithms = {
            request.algorithm
            for request in requests
            if request.tier == "update_performance"
        }
        self.assertEqual(update_algorithms, {"weighted_sssp"})
        endpoints = [
            request
            for request in requests
            if request.tier == "endpoint_scalability"
        ]
        self.assertEqual(len(endpoints), 12)
        self.assertEqual(
            {request.dataset_id for request in endpoints}, {"rmat_19_32"}
        )

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

    def test_primary_k4_must_keep_one_shared_downstream(self) -> None:
        direct = deepcopy(self.contract)
        baseline = direct["architecture_baselines"]["grasu_regraph_k4_shared"]
        baseline["downstream_paths"] = 4
        baseline["shared_hbm_arbitration"] = False
        with self.assertRaisesRegex(ValueError, "shared-downstream"):
            validate_large_graph_campaign_contract(direct)

    def test_direct_k4_cannot_enter_headline_aggregate(self) -> None:
        promoted = deepcopy(self.contract)
        promoted["architecture_baselines"]["grasu_regraph_k4_ideal"][
            "eligible_for_headline_aggregate"
        ] = True
        with self.assertRaisesRegex(ValueError, "upper-bound"):
            validate_large_graph_campaign_contract(promoted)

    def test_capability_catalog_identity_is_frozen(self) -> None:
        changed = deepcopy(self.contract)
        changed["architecture_baselines"]["grasu_regraph_capability_catalog"][
            "sha256"
        ] = "0" * 64
        self.assertRaisesRegex(
            ValueError,
            "common platform",
            validate_large_graph_campaign_contract,
            changed,
        )

    def test_automatic_timeout_and_compact_ids_are_rejected(self) -> None:
        timed = deepcopy(self.contract)
        timed["execution"]["automatic_timeout_seconds"] = 3600
        with self.assertRaisesRegex(ValueError, "soft-stop"):
            validate_large_graph_campaign_contract(timed)
        compact = deepcopy(self.contract)
        compact["workload_semantics"]["preserve_external_vertex_ids"] = False
        with self.assertRaisesRegex(ValueError, "external vertex IDs"):
            validate_large_graph_campaign_contract(compact)
        changed_update = deepcopy(self.contract)
        changed_update["experiment_matrix"]["update_performance"][
            "execution_algorithm"
        ] = "full_pagerank"
        with self.assertRaisesRegex(ValueError, "update-throughput"):
            validate_large_graph_campaign_contract(changed_update)

    def test_spine_vertex_capacity_is_fail_closed_before_launch(self) -> None:
        manifest = {"capacity": {"spine_max_vertices": 1 << 24}}
        self.assertTrue(
            spine_profile_vertex_admitted(
                manifest, system="spine", vertices=1 << 24
            )
        )
        self.assertFalse(
            spine_profile_vertex_admitted(
                manifest, system="spine", vertices=(1 << 24) + 1
            )
        )
        self.assertTrue(
            spine_profile_vertex_admitted(
                manifest, system="grasu_regraph_k1", vertices=(1 << 24) + 1
            )
        )
        with self.assertRaisesRegex(ValueError, "positive"):
            spine_profile_vertex_admitted(manifest, system="spine", vertices=0)
        with self.assertRaisesRegex(ValueError, "spine_max_vertices"):
            spine_profile_vertex_admitted({}, system="spine", vertices=1)

    def test_formal_campaign_rejects_unknown_selection_filters(self) -> None:
        common = {
            "materialization_root": Path("/tmp/publication-workloads"),
            "output_root": Path("/tmp/publication-runs"),
            "python": "python3",
            "sst": Path("/tmp/sst"),
            "lib_dir": Path("/tmp/plugin"),
            "capability_catalog": Path("/tmp/catalog.json"),
        }
        with self.assertRaisesRegex(ValueError, "algorithms"):
            build_publication_experiment_campaign_manifest(
                self.contract,
                selected_algorithms={"not_an_algorithm"},
                **common,
            )
        with self.assertRaisesRegex(ValueError, "systems"):
            build_publication_experiment_campaign_manifest(
                self.contract,
                selected_systems={"not_a_system"},
                **common,
            )
        with self.assertRaisesRegex(ValueError, "scenarios"):
            build_publication_experiment_campaign_manifest(
                self.contract,
                selected_scenarios={"not_a_scenario"},
                **common,
            )
        with self.assertRaisesRegex(ValueError, "batch sizes"):
            build_publication_experiment_campaign_manifest(
                self.contract,
                selected_batch_sizes={999},
                **common,
            )
        with self.assertRaisesRegex(ValueError, "source cohort override"):
            build_publication_experiment_campaign_manifest(
                self.contract,
                source_cohort_override="",
                **common,
            )


if __name__ == "__main__":
    unittest.main()
