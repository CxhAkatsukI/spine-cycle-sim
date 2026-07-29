from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.profile_capabilities import (
    CapabilityError,
    ImplementationStatus,
    load_capability_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG = (
    ROOT / "configs" / "contracts" / "grasu_regraph_capabilities_v1.json"
)
CATALOG_V2 = (
    ROOT
    / "configs"
    / "contracts"
    / "grasu_regraph_candidate10_capabilities_v2.json"
)
CATALOG_V3 = (
    ROOT
    / "configs"
    / "contracts"
    / "grasu_regraph_candidate10_hls_capabilities_v3.json"
)
CATALOG_V4 = (
    ROOT
    / "configs"
    / "contracts"
    / "grasu_regraph_k1_multipart_capabilities_v4.json"
)
CATALOG_V5 = (
    ROOT
    / "configs"
    / "contracts"
    / "grasu_regraph_runtime_packed_capabilities_v5.json"
)
CATALOG_V6 = (
    ROOT
    / "configs"
    / "contracts"
    / "grasu_regraph_publication_capabilities_v6.json"
)
CATALOG_V7 = (
    ROOT
    / "configs"
    / "contracts"
    / "grasu_regraph_full_graph_capabilities_v7.json"
)


class ProfileCapabilityTests(unittest.TestCase):
    def test_catalog_covers_every_grasu_regraph_profile(self) -> None:
        catalogs = (
            load_capability_catalog(CATALOG),
            load_capability_catalog(CATALOG_V2),
            load_capability_catalog(CATALOG_V3),
            load_capability_catalog(CATALOG_V4),
            load_capability_catalog(CATALOG_V5),
            load_capability_catalog(CATALOG_V6),
            load_capability_catalog(CATALOG_V7),
        )
        profile_ids = {
            json.loads(path.read_text(encoding="utf-8"))["profile_id"]
            for path in (ROOT / "configs" / "architectures").glob(
                "grasu_regraph_*.json"
            )
        }
        covered = set().union(*(set(catalog.profiles) for catalog in catalogs))
        self.assertEqual(covered, profile_ids)
        for catalog in catalogs:
            for profile in catalog.profiles.values():
                self.assertEqual(
                    set(profile.supported_algorithms)
                    | set(profile.unsupported_algorithms),
                    set(catalog.algorithms),
                )

    def test_native_support_is_only_existing_hls_unit_sssp(self) -> None:
        native = load_capability_catalog(CATALOG).profile(
            "grasu_regraph_native_a9aef06"
        )
        capability = native.require("unit_weight_sssp")
        self.assertEqual(
            capability.implementation_status, ImplementationStatus.EXECUTABLE
        )
        self.assertEqual(capability.evidence_tier, "hardware_validated")
        self.assertEqual(native.handoff, "pma_to_compact_edge_array")
        self.assertEqual(native.conversion_cost, "included")
        for algorithm in (
            "weighted_sssp",
            "weighted_dynamic_sssp",
            "full_pagerank",
            "thresholded_residual_pagerank",
        ):
            with self.subTest(algorithm=algorithm):
                with self.assertRaisesRegex(CapabilityError, "does not support"):
                    native.require(algorithm)

    def test_weighted_hls_sw_emu_profile_is_executable(self) -> None:
        profile = load_capability_catalog(CATALOG).profile(
            "grasu_regraph_weighted_pma_hls_sw_emu_ff13a67"
        )
        self.assertEqual(profile.comparison_role, "hls_sw_emu")
        self.assertEqual(profile.handoff, "weighted_pma_to_axis_stream")
        self.assertEqual(profile.conversion_cost, "absent")
        for algorithm in ("weighted_sssp", "weighted_dynamic_sssp"):
            with self.subTest(algorithm=algorithm):
                descriptive = profile.require(algorithm)
                self.assertEqual(
                    descriptive.implementation_status,
                    ImplementationStatus.EXECUTABLE,
                )
                self.assertEqual(descriptive.evidence_tier, "emulation_validated")
                self.assertEqual(
                    descriptive.claim_class,
                    "hls_sw_emu_aligned_execution_driven_simulation",
                )
        for algorithm in (
            "unit_weight_sssp",
            "full_pagerank",
            "thresholded_residual_pagerank",
        ):
            with self.subTest(algorithm=algorithm):
                with self.assertRaisesRegex(CapabilityError, "does not support"):
                    profile.require(algorithm)

    def test_normalized_three_algorithm_profiles_are_executable(self) -> None:
        catalog = load_capability_catalog(CATALOG)
        cases = (
            ("grasu_regraph_normalized_weighted_spine23", "weighted_sssp"),
            (
                "grasu_regraph_normalized_weighted_spine23",
                "weighted_dynamic_sssp",
            ),
            ("grasu_regraph_normalized_pagerank_spine23", "full_pagerank"),
            (
                "grasu_regraph_normalized_residual_pagerank_spine23",
                "thresholded_residual_pagerank",
            ),
        )
        for profile_id, algorithm in cases:
            with self.subTest(profile_id=profile_id, algorithm=algorithm):
                capability = catalog.profile(profile_id).require(algorithm)
                self.assertEqual(
                    capability.implementation_status,
                    ImplementationStatus.EXECUTABLE,
                )
                self.assertEqual(capability.evidence_tier, "simulation_only")

    def test_candidate10_v2_three_algorithm_profiles_are_executable(self) -> None:
        catalog = load_capability_catalog(CATALOG_V2)
        cases = (
            ("grasu_regraph_candidate10_normalized_weighted_v2", "weighted_sssp"),
            (
                "grasu_regraph_candidate10_normalized_weighted_v2",
                "weighted_dynamic_sssp",
            ),
            (
                "grasu_regraph_candidate10_normalized_pagerank_v2",
                "full_pagerank",
            ),
            (
                "grasu_regraph_candidate10_normalized_residual_pagerank_v2",
                "thresholded_residual_pagerank",
            ),
        )
        for profile_id, algorithm in cases:
            with self.subTest(profile_id=profile_id, algorithm=algorithm):
                capability = catalog.profile(profile_id).require(algorithm)
                self.assertEqual(
                    capability.implementation_status,
                    ImplementationStatus.EXECUTABLE,
                )
                self.assertEqual(
                    capability.claim_class,
                    "candidate10_derived_normalized_structural_simulation",
                )

    def test_proposed_hls_pagerank_profile_is_explicitly_simulation_only(self) -> None:
        profile = load_capability_catalog(CATALOG).profile(
            "grasu_regraph_weighted_pma_hls_proposed_pagerank_ff13a67"
        )
        capability = profile.require("full_pagerank")
        self.assertEqual(profile.comparison_role, "hls_equivalent_proposed")
        self.assertEqual(profile.handoff, "weighted_pma_to_axis_stream")
        self.assertEqual(profile.conversion_cost, "absent")
        self.assertEqual(
            capability.implementation_status, ImplementationStatus.EXECUTABLE
        )
        self.assertEqual(capability.evidence_tier, "simulation_only")
        self.assertEqual(
            capability.claim_class,
            "hls_equivalent_proposed_execution_driven_simulation",
        )

    def test_proposed_hls_residual_profile_is_executable(self) -> None:
        profile = load_capability_catalog(CATALOG).profile(
            "grasu_regraph_weighted_pma_hls_proposed_residual_pagerank_ff13a67"
        )
        capability = profile.require("thresholded_residual_pagerank")
        self.assertEqual(profile.comparison_role, "hls_equivalent_proposed")
        self.assertEqual(
            capability.implementation_status, ImplementationStatus.EXECUTABLE
        )
        self.assertEqual(capability.evidence_tier, "simulation_only")
        self.assertEqual(
            capability.convergence,
            "signed_residual_threshold_or_iteration_limit",
        )

    def test_projected_profile_is_not_an_executable_implementation(self) -> None:
        projected = load_capability_catalog(CATALOG).profile(
            "grasu_regraph_weighted_pma_native_projected"
        )
        with self.assertRaisesRegex(CapabilityError, "profile_only"):
            projected.require("weighted_sssp")
        self.assertEqual(
            projected.require("weighted_sssp", executable=False).implementation_status,
            ImplementationStatus.PROFILE_ONLY,
        )

    def test_profile_hash_mismatch_fails_closed(self) -> None:
        payload = json.loads(CATALOG.read_text(encoding="utf-8"))
        payload["profiles"][0]["profile_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / "capabilities.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(CapabilityError, "profile hash mismatch"):
                load_capability_catalog(path, repository_root=ROOT)


if __name__ == "__main__":
    unittest.main()
