from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.profiles import (
    EvidenceTier,
    ProfileError,
    ProfileStatus,
    load_architecture_profile,
    verify_profile_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "configs" / "architectures"


class ArchitectureProfileTests(unittest.TestCase):
    def test_weighted_pma_hls_sw_emu_profile_freezes_real_topology(self) -> None:
        profile = load_architecture_profile(
            ROOT
            / "configs"
            / "architectures"
            / "grasu_regraph_weighted_pma_hls_sw_emu_ff13a67.json"
        )
        self.assertEqual(profile.evidence_tier, EvidenceTier.EMULATION_VALIDATED)
        self.assertEqual(profile.parameters["comparison_role"], "hls_sw_emu")
        self.assertEqual(profile.parameters["hls_compute_units"], 15)
        self.assertEqual(profile.parameters["regraph_map_reduce_lanes"], 8)
        self.assertEqual(
            profile.parameters["grasu_pma_edge_abi"],
            "regraph_weighted32_full_word_compare_dst19_weight12",
        )
        self.assertEqual(
            profile.parameters["grasu_weight_change_lowering"],
            "delete_old_word_then_insert_new_word",
        )
        self.assertEqual(profile.parameters["hls_validation_supersteps"], 4)
        self.assertTrue(profile.parameters["pma_native_compute"])
        self.assertFalse(profile.parameters["conversion_cost_included"])
        self.assertEqual(profile.memory.max_outstanding_per_port, 16)
        evidence = {artifact.kind: artifact for artifact in profile.evidence}
        self.assertEqual(
            evidence["sw_emu_xclbin_identity"].sha256,
            "3e819201c8846299a0b5f40ed66be7043fa6f2b1e97bdc7dbba2e2171edaa0ba",
        )

    def test_repository_profiles_load_and_have_unique_ids(self) -> None:
        loaded = [load_architecture_profile(path) for path in sorted(PROFILES.glob("*.json"))]
        self.assertEqual(len(loaded), 48)
        self.assertEqual(len({profile.profile_id for profile in loaded}), len(loaded))
        self.assertTrue(all(profile.manifest_sha256 for profile in loaded))
        packed_ids = {
            profile.profile_id
            for profile in loaded
            if profile.parameters.get("grasu_partition_address_layout")
            == "runtime_packed_v1"
        }
        self.assertEqual(len(packed_ids), 15)

    def test_candidate10_profile_pins_frozen_dirty_source_and_routed_xclbin(
        self,
    ) -> None:
        profile = load_architecture_profile(
            PROFILES / "spine_candidate10_one_pass_1e61fc0.json"
        )
        self.assertEqual(profile.status, ProfileStatus.STABLE)
        self.assertEqual(profile.evidence_tier, EvidenceTier.HARDWARE_VALIDATED)
        self.assertTrue(profile.source.dirty)
        self.assertEqual(
            profile.parameters["maintenance_architecture"],
            "candidate10_one_pass",
        )
        self.assertEqual(profile.parameters["metadata_format_version"], 5)
        self.assertEqual(profile.parameters["result_layout_version"], 6)
        self.assertEqual(profile.parameters["classification_block_edges"], 128)
        self.assertEqual(profile.clock("data").achieved_mhz, 150.0)
        evidence = {artifact.kind: artifact for artifact in profile.evidence}
        self.assertEqual(
            evidence["frozen_hls_source"].sha256,
            "d98fb04cb59c3b00b894ba4d615d7dd1a6250f46fe1d998a951bb0a0843c7dbc",
        )
        self.assertEqual(
            evidence["routed_xclbin"].sha256,
            "551ed1e89755a8b97725efa4003e28007eabd66abb73f480c6ee087a627b9666",
        )
        self.assertEqual(verify_profile_artifacts(profile), [])

    def test_candidate10_normalized_profile_preserves_native_lineage(self) -> None:
        parent = load_architecture_profile(
            PROFILES / "spine_candidate10_one_pass_1e61fc0.json"
        )
        normalized = load_architecture_profile(
            PROFILES / "spine_candidate10_normalized_v1.json"
        )
        self.assertEqual(normalized.parameters["comparison_role"], "normalized")
        self.assertEqual(
            normalized.parameters["native_parent_profile"], parent.profile_id
        )
        self.assertEqual(
            normalized.parameters["native_parent_profile_sha256"],
            parent.manifest_sha256,
        )
        self.assertEqual(
            normalized.parameters["maintenance_architecture"],
            "candidate10_one_pass",
        )
        self.assertEqual(
            normalized.parameters["axi_profile"], "candidate10_gmem_1e61fc0"
        )

    def test_candidate10_opt_v1_is_an_explicit_projected_delta(self) -> None:
        normalized = load_architecture_profile(
            PROFILES / "spine_candidate10_normalized_v1.json"
        )
        optimized = load_architecture_profile(
            PROFILES / "spine_candidate10_opt_v1_fallback_level_cache.json"
        )
        self.assertEqual(optimized.status, ProfileStatus.PROJECTED)
        self.assertEqual(optimized.evidence_tier, EvidenceTier.SYNTHESIS_ONLY)
        self.assertEqual(
            optimized.parameters["simulation_parent_profile"],
            normalized.profile_id,
        )
        self.assertEqual(
            optimized.parameters["simulation_parent_profile_sha256"],
            normalized.manifest_sha256,
        )
        self.assertTrue(optimized.parameters["fallback_level_cache_reuse"])
        self.assertEqual(
            optimized.parameters["optimization_id"],
            "fallback_launch_level_cache_reuse",
        )
        self.assertEqual(
            optimized.parameters["resource_feasibility_gate"],
            "candidate10_opt_v1_readmaint_csynth_resource_pass_timing_open",
        )
        self.assertEqual(verify_profile_artifacts(optimized), [])

    def test_candidate10_opt_v2_freezes_finite_reader_working_set(self) -> None:
        parent = load_architecture_profile(
            PROFILES / "spine_candidate10_opt_v1_fallback_level_cache.json"
        )
        optimized = load_architecture_profile(
            PROFILES / "spine_candidate10_opt_v2_reader_working_set.json"
        )
        self.assertEqual(optimized.status, ProfileStatus.PROJECTED)
        self.assertEqual(optimized.evidence_tier, EvidenceTier.SYNTHESIS_ONLY)
        self.assertEqual(
            optimized.parameters["simulation_parent_profile"],
            parent.profile_id,
        )
        self.assertEqual(
            optimized.parameters["simulation_parent_profile_sha256"],
            parent.manifest_sha256,
        )
        self.assertTrue(optimized.parameters["fallback_level_cache_reuse"])
        self.assertTrue(optimized.parameters["source_page_index_cache"])
        self.assertEqual(optimized.parameters["range_task_active_gate"], 32_768)
        self.assertEqual(
            optimized.parameters["source_page_cache_entries_per_fixed_family"],
            11,
        )
        self.assertEqual(
            optimized.parameters["range_task_active_cache_added_bytes"],
            393_216,
        )
        self.assertEqual(
            optimized.parameters["resource_feasibility_gate"],
            "focused_hls_csynth_complete_timing_target_missed",
        )
        self.assertEqual(optimized.parameters["optimized_readmaint_uram"], 100)
        self.assertEqual(verify_profile_artifacts(optimized), [])

    def test_stable_profile_pins_accepted_clocks_and_hash(self) -> None:
        profile = load_architecture_profile(PROFILES / "spine_shared_engine_9c08763.json")
        self.assertEqual(profile.status, ProfileStatus.STABLE)
        self.assertEqual(profile.evidence_tier, EvidenceTier.HARDWARE_VALIDATED)
        self.assertEqual(profile.clock("data").requested_mhz, 150.0)
        self.assertEqual(profile.clock("data").achieved_mhz, 141.0)
        self.assertEqual(profile.clock("hbm").achieved_mhz, 450.0)
        self.assertEqual(profile.memory.channels, 32)
        self.assertEqual(profile.parameters["graph_hbm_channels"], 16)
        self.assertEqual(profile.parameters["hbm_pseudo_channels_used"], 23)
        self.assertEqual(profile.parameters["sorted_edges_hbm_channel"], 16)
        self.assertEqual(profile.parameters["active_bitmap_hbm_channel"], 22)
        self.assertEqual(
            profile.evidence[2].sha256,
            "1828434e164bf0aef28fff9fba7925cfa39f93ad86f6bfc3878f504461c76dbf",
        )

    def test_stable_profile_artifacts_exist_and_match(self) -> None:
        profile = load_architecture_profile(PROFILES / "spine_shared_engine_9c08763.json")
        self.assertEqual(verify_profile_artifacts(profile), [])

    def test_unknown_root_field_is_rejected(self) -> None:
        source = json.loads((PROFILES / "spine_latest_afb8199.json").read_text())
        source["typo"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "unknown=typo"):
                load_architecture_profile(path)

    def test_duplicate_clock_is_rejected(self) -> None:
        source = json.loads((PROFILES / "spine_latest_afb8199.json").read_text())
        source["clocks"].append(dict(source["clocks"][0]))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "duplicate clock"):
                load_architecture_profile(path)

    def test_dirty_must_be_boolean(self) -> None:
        source = json.loads((PROFILES / "spine_latest_afb8199.json").read_text())
        source["source"]["dirty"] = "false"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "must be boolean"):
                load_architecture_profile(path)

    def test_grasu_regraph_profiles_freeze_comparison_roles(self) -> None:
        native = load_architecture_profile(
            PROFILES / "grasu_regraph_native_a9aef06.json"
        )
        normalized = load_architecture_profile(
            PROFILES / "grasu_regraph_normalized_spine23.json"
        )
        projected = load_architecture_profile(
            PROFILES / "grasu_regraph_pma_native_projected.json"
        )
        weighted_normalized = load_architecture_profile(
            PROFILES / "grasu_regraph_normalized_weighted_spine23.json"
        )
        weighted_projected = load_architecture_profile(
            PROFILES / "grasu_regraph_weighted_pma_native_projected.json"
        )
        pagerank_normalized = load_architecture_profile(
            PROFILES / "grasu_regraph_normalized_pagerank_spine23.json"
        )
        residual_normalized = load_architecture_profile(
            PROFILES
            / "grasu_regraph_normalized_residual_pagerank_spine23.json"
        )
        partitioned_dynamic = load_architecture_profile(
            PROFILES
            / "grasu_regraph_partitioned_dynamic_pagerank_spine23.json"
        )
        hls_proposed_pagerank = load_architecture_profile(
            PROFILES
            / "grasu_regraph_weighted_pma_hls_proposed_pagerank_ff13a67.json"
        )
        hls_proposed_residual = load_architecture_profile(
            PROFILES
            / "grasu_regraph_weighted_pma_hls_proposed_residual_pagerank_ff13a67.json"
        )

        self.assertEqual(native.parameters["comparison_role"], "native")
        self.assertFalse(native.parameters["pma_native_compute"])
        self.assertTrue(native.parameters["conversion_cost_included"])
        self.assertEqual(normalized.parameters["comparison_role"], "normalized")
        self.assertTrue(normalized.parameters["pma_native_compute"])
        self.assertEqual(normalized.parameters["hbm_pseudo_channels_budget"], 23)
        self.assertEqual(normalized.clock("kernel").achieved_mhz, 150.0)
        self.assertEqual(normalized.parameters["regraph_source_state_channel"], 1)
        self.assertEqual(
            normalized.parameters["regraph_source_state_mirror_channel"], 3
        )
        self.assertEqual(normalized.parameters["regraph_apply_state_channel"], 30)
        self.assertEqual(normalized.parameters["regraph_source_state_copies"], 2)
        self.assertEqual(
            normalized.parameters["regraph_source_buffer_vertices"], 4096
        )
        self.assertEqual(
            normalized.parameters["regraph_source_cache_request_fifo_depth"], 8
        )
        self.assertEqual(
            normalized.parameters["regraph_source_cache_response_fifo_depth"], 8
        )
        self.assertEqual(
            normalized.parameters["regraph_gather_bypass_distance"], 6
        )
        self.assertEqual(
            normalized.parameters["regraph_gather_pipeline_latency"], 9
        )
        self.assertEqual(
            normalized.parameters["regraph_gather_merger_fifo_depth"], 16
        )
        self.assertEqual(normalized.parameters["regraph_merger_apply_fifo_depth"], 16)
        self.assertEqual(
            normalized.parameters["regraph_apply_wrapper_fifo_depth"], 16
        )
        self.assertEqual(
            normalized.parameters["regraph_hbm_wrapper_pipeline_latency"], 71
        )
        self.assertEqual(
            normalized.parameters["regraph_hbm_wrapper_pipeline_capacity"], 71
        )
        self.assertEqual(projected.parameters["comparison_role"], "projected")
        self.assertTrue(projected.parameters["change_aware_compute_activation"])
        self.assertEqual(
            weighted_normalized.parameters["grasu_pma_edge_abi"],
            "regraph_weighted32_dst19_weight12",
        )
        self.assertEqual(
            weighted_projected.parameters["grasu_pma_edge_abi"],
            "regraph_weighted32_dst19_weight12",
        )
        self.assertEqual(
            pagerank_normalized.parameters["regraph_degree_channel"], 30
        )
        self.assertEqual(
            pagerank_normalized.parameters["regraph_pagerank_source_map_latency"],
            3,
        )
        self.assertEqual(
            hls_proposed_pagerank.parameters["comparison_role"],
            "hls_equivalent_proposed",
        )
        self.assertEqual(hls_proposed_pagerank.clock("kernel").achieved_mhz, 200.0)
        self.assertEqual(
            hls_proposed_pagerank.parameters["grasu_pma_edge_abi"],
            "regraph_weighted32_full_word_compare_dst19_weight12",
        )
        self.assertEqual(
            hls_proposed_pagerank.parameters["regraph_map_reduce_lanes"], 8
        )
        self.assertTrue(
            hls_proposed_pagerank.parameters["pagerank_degree_update_timing"]
        )
        self.assertFalse(
            hls_proposed_pagerank.parameters["conversion_cost_included"]
        )
        self.assertEqual(
            hls_proposed_residual.parameters["comparison_role"],
            "hls_equivalent_proposed",
        )
        self.assertEqual(
            hls_proposed_residual.parameters["pagerank_state_bytes_per_vertex"],
            8,
        )
        self.assertEqual(
            hls_proposed_residual.parameters["pagerank_activation_rule"],
            "abs_residual_gt_epsilon_over_vertices",
        )
        self.assertTrue(
            hls_proposed_residual.parameters["pagerank_degree_update_timing"]
        )
        self.assertTrue(
            pagerank_normalized.parameters["pagerank_degree_reads_timed"]
        )
        self.assertFalse(
            pagerank_normalized.parameters["pagerank_degree_update_timing"]
        )
        self.assertEqual(
            residual_normalized.parameters["pagerank_state_layout"],
            "packed_float32_rank_residual_64",
        )
        self.assertEqual(
            residual_normalized.parameters["pagerank_state_bytes_per_vertex"], 8
        )
        self.assertEqual(
            residual_normalized.parameters["pagerank_activation_rule"],
            "abs_residual_gt_epsilon_over_vertices",
        )
        self.assertEqual(
            residual_normalized.parameters["pagerank_epsilon"], 1.0e-6
        )
        self.assertFalse(
            residual_normalized.parameters["pagerank_degree_update_timing"]
        )
        self.assertEqual(
            partitioned_dynamic.parameters["comparison_role"], "normalized"
        )
        self.assertEqual(
            partitioned_dynamic.parameters["grasu_update_record_bytes"], 16
        )
        self.assertTrue(
            partitioned_dynamic.parameters[
                "grasu_update_global_destination_routing"
            ]
        )
        self.assertEqual(
            partitioned_dynamic.parameters["regraph_compute_pipelines"], 1
        )
        self.assertEqual(
            partitioned_dynamic.parameters["regraph_partition_execution"],
            "serial",
        )
        self.assertTrue(
            partitioned_dynamic.parameters["pagerank_degree_update_timing"]
        )
        self.assertEqual(
            partitioned_dynamic.parameters["grasu_degree_reorder_entries"],
            4096,
        )
        self.assertFalse(
            partitioned_dynamic.parameters["conversion_cost_included"]
        )
        channel_bytes = partitioned_dynamic.memory.channel_capacity_bytes
        address_fields = (
            "grasu_update_base_bytes",
            "grasu_binary_base_bytes",
            "grasu_row_offset_base_bytes",
            "grasu_pma_base_bytes",
            "grasu_vertex_state_base_bytes",
            "grasu_source_state_base_bytes",
            "grasu_degree_base_bytes",
        )
        self.assertTrue(
            all(
                0 <= partitioned_dynamic.parameters[field] < channel_bytes
                for field in address_fields
            )
        )
        self.assertNotEqual(
            partitioned_dynamic.parameters["grasu_partition_address_stride_bytes"]
            % channel_bytes,
            0,
        )
        self.assertEqual(
            partitioned_dynamic.parameters[
                "max_destination_partitions_without_address_remap"
            ],
            4,
        )

    def test_grasu_native_profile_matches_hls_topology(self) -> None:
        profile = load_architecture_profile(
            PROFILES / "grasu_regraph_native_a9aef06.json"
        )
        self.assertEqual(profile.parameters["grasu_bin_search_cus"], 4)
        self.assertEqual(
            profile.parameters["grasu_binary_search_workers_per_cu"], 1
        )
        self.assertTrue(profile.parameters["grasu_compact_hbm_ports"])
        self.assertEqual(profile.parameters["grasu_process_cache_cus"], 2)
        self.assertEqual(profile.parameters["grasu_process_ddr_cus"], 2)
        self.assertEqual(profile.parameters["grasu_cache_lanes_per_cu"], 1)
        self.assertTrue(profile.parameters["grasu_direct_cache_hbm_rmw"])
        self.assertEqual(profile.parameters["grasu_ddr_halves_per_cu"], 2)
        self.assertEqual(profile.parameters["grasu_ddr_lanes_per_half"], 16)
        self.assertEqual(profile.parameters["grasu_segment_slots"], 16)
        self.assertEqual(profile.parameters["regraph_partition_vertices"], 65536)
        self.assertEqual(profile.parameters["regraph_map_reduce_lanes"], 8)
        self.assertEqual(profile.parameters["regraph_edge_array_fifo_depth"], 8)
        self.assertEqual(profile.parameters["regraph_source_buffer_vertices"], 4096)
        self.assertEqual(profile.parameters["regraph_source_state_channel"], 1)
        self.assertEqual(
            profile.parameters["regraph_source_state_mirror_channel"], 3
        )
        self.assertEqual(profile.parameters["regraph_vertex_prop_hbm_channel"], 30)
        active_channels = {
            *range(
                profile.parameters["grasu_pma_hbm_first_channel"],
                profile.parameters["grasu_pma_hbm_first_channel"]
                + profile.parameters["grasu_pma_hbm_channels"],
            ),
            profile.parameters["pma_compactor_row_channel"],
            profile.parameters["regraph_edge_array_channel"],
            profile.parameters["regraph_source_state_channel"],
            profile.parameters["regraph_source_state_mirror_channel"],
            profile.parameters["regraph_vertex_prop_hbm_channel"],
        }
        self.assertEqual(active_channels, {0, 1, 2, 3, 30})
        self.assertEqual(profile.memory.channels, 32)
        self.assertIn("native_host_vertex_reorder", profile.features)
        self.assertTrue(profile.parameters["conversion_cost_included"])
        self.assertFalse(profile.parameters["pma_native_compute"])
        self.assertEqual(verify_profile_artifacts(profile), [])


if __name__ == "__main__":
    unittest.main()
