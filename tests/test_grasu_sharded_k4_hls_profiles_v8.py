from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest

from scripts.run_sst_grasu_regraph_hls_residual_pagerank import (
    require_hls_residual_capability,
)
from scripts.run_sst_grasu_regraph_hls_weighted import (
    require_hls_weighted_capability,
)
from spine_cycle_sim.experiments.profile_capabilities import (
    load_capability_catalog,
)
from spine_cycle_sim.profiles import load_architecture_profile
from spine_cycle_sim.sst_binding import grasu_normalized_memory_binding


ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "configs" / "architectures"
CATALOG = ROOT / "configs" / "contracts" / "grasu_regraph_sharded_k4_hls_capabilities_v8.json"
PROFILES = {
    "weighted": ARCH / "grasu_regraph_sharded_k4_weighted_hls_v8.json",
    "cc": ARCH / "grasu_regraph_sharded_k4_cc_hls_v8.json",
    "residual": ARCH / "grasu_regraph_sharded_k4_residual_hls_v8.json",
}


class GraSuShardedK4HlsProfilesV8Tests(unittest.TestCase):
    def test_generated_artifacts_are_current(self) -> None:
        subprocess.run(
            [
                "python3",
                str(ROOT / "scripts" / "generate_grasu_regraph_sharded_k4_hls_profiles_v8.py"),
                "--check",
            ],
            cwd=ROOT,
            check=True,
        )

    def test_catalog_and_profile_evidence_are_hash_pinned(self) -> None:
        catalog = load_capability_catalog(CATALOG, repository_root=ROOT)
        self.assertEqual(len(catalog.profiles), 3)
        for path in PROFILES.values():
            profile = load_architecture_profile(path)
            self.assertEqual(profile.status.value, "stable")
            self.assertEqual(profile.evidence_tier.value, "hardware_validated")

    def test_common_topology_matches_routed_hls(self) -> None:
        for path in PROFILES.values():
            profile = json.loads(path.read_text(encoding="utf-8"))
            params = profile["parameters"]
            self.assertEqual(params["grasu_partition_address_layout"], "destination_sharded_local_dst19_v1")
            self.assertTrue(params["grasu_sharded_runtime_placement"])
            self.assertEqual(params["grasu_pma_hbm_channels"], 23)
            self.assertEqual(params["regraph_compute_pipelines"], 4)
            self.assertEqual(params["regraph_downstream_sharing"], "shared")
            self.assertEqual(params["regraph_source_state_channel"], 23)
            self.assertEqual(params["regraph_source_state_mirror_channel"], 24)
            self.assertNotIn("physical_address_map_id", params)

    def test_reachable_channels_match_each_routed_algorithm(self) -> None:
        weighted = json.loads(PROFILES["weighted"].read_text(encoding="utf-8"))
        residual = json.loads(PROFILES["residual"].read_text(encoding="utf-8"))
        self.assertEqual(
            grasu_normalized_memory_binding(weighted).reachable_channels,
            tuple(range(25)) + (30,),
        )
        self.assertEqual(
            grasu_normalized_memory_binding(residual).reachable_channels,
            tuple(range(28)),
        )

    def test_residual_profile_freezes_split_hardware_state(self) -> None:
        profile = json.loads(PROFILES["residual"].read_text(encoding="utf-8"))
        params = profile["parameters"]
        self.assertTrue(params["regraph_split_pagerank_state"])
        self.assertEqual(params["regraph_apply_state_channel"], 25)
        self.assertEqual(params["regraph_residual_state_channel"], 26)
        self.assertEqual(params["regraph_degree_channel"], 27)
        self.assertEqual(params["pagerank_activation_rule"], "abs_residual_gt_epsilon")

    def test_hls_runners_accept_hardware_native_capabilities(self) -> None:
        _catalog, weighted = require_hls_weighted_capability(
            PROFILES["weighted"], CATALOG, "weighted_dynamic_sssp"
        )
        _catalog, residual = require_hls_residual_capability(
            PROFILES["residual"], CATALOG
        )
        self.assertEqual(weighted.evidence_tier, "hardware_validated")
        self.assertEqual(residual.evidence_tier, "hardware_validated")


if __name__ == "__main__":
    unittest.main()
