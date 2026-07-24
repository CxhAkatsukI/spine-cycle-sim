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
    def test_repository_profiles_load_and_have_unique_ids(self) -> None:
        loaded = [load_architecture_profile(path) for path in sorted(PROFILES.glob("*.json"))]
        self.assertEqual(len(loaded), 8)
        self.assertEqual(len({profile.profile_id for profile in loaded}), len(loaded))
        self.assertTrue(all(profile.manifest_sha256 for profile in loaded))

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
        self.assertEqual(verify_profile_artifacts(profile), [])


if __name__ == "__main__":
    unittest.main()
