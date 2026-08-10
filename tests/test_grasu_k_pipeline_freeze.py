from __future__ import annotations

import json
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.comparison import (
    normalized_grasu_capability_catalog_path,
    normalized_grasu_profile_paths,
    validate_normalized_profile_contract,
)
from spine_cycle_sim.experiments.feasibility import (
    load_normalized_hls_feasibility,
)
from spine_cycle_sim.experiments.grasu_addressing import (
    required_source_state_stride_bytes,
    validate_grasu_hbm_address_map,
)
from spine_cycle_sim.experiments.profile_capabilities import (
    load_capability_catalog,
)
from spine_cycle_sim.profiles import EvidenceTier, load_architecture_profile


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT / "configs/contracts/grasu_regraph_k_pipeline_freeze_v1.json"
)
FEASIBILITY = (
    ROOT
    / "configs/contracts/candidate10_k1_multipart_hls_feasibility_v3.json"
)


class GraSuKPipelineFreezeTests(unittest.TestCase):
    def test_k1_is_frozen_before_holdout_from_port_feasibility(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["selection"]["compute_pipelines"], 1)
        self.assertTrue(contract["selection"]["frozen_before_holdout"])
        self.assertEqual(contract["selection"]["address_validated_partitions"], 4)
        for algorithm, projection in contract["projections"].items():
            with self.subTest(algorithm=algorithm):
                candidates = {
                    item["compute_pipelines"]: item
                    for item in projection["candidates"]
                }
                self.assertTrue(candidates[1]["master_budget_passed"])
                self.assertEqual(candidates[1]["hls_evidence"], "routed")
                self.assertFalse(candidates[2]["master_budget_passed"])
                self.assertFalse(candidates[4]["master_budget_passed"])
                self.assertTrue(candidates[4]["resource_ceiling_passed"])
                self.assertEqual(candidates[2]["hls_evidence"], "not_synthesized")

    def test_v4_profiles_and_capabilities_are_consistent(self) -> None:
        paths = normalized_grasu_profile_paths(ROOT, "k1_v4")
        profiles = tuple(load_architecture_profile(path) for path in paths)
        self.assertEqual(len(profiles), 3)
        for profile in profiles:
            with self.subTest(profile=profile.profile_id):
                self.assertEqual(profile.evidence_tier, EvidenceTier.SYNTHESIS_ONLY)
                self.assertEqual(profile.parameters["regraph_compute_pipelines"], 1)
                self.assertEqual(
                    profile.parameters["regraph_partition_execution"],
                    "finite_work_conserving_serial_k1",
                )
                self.assertEqual(profile.parameters["regraph_destination_partitions"], 16)
                self.assertEqual(
                    profile.parameters["physical_address_map_id"],
                    "candidate10_hbm_pc_nonalias_v1",
                )
                self.assertEqual(
                    profile.parameters["grasu_source_state_buffer_stride_bytes"],
                    required_source_state_stride_bytes(profile.parameters, 4),
                )
                validate_grasu_hbm_address_map(
                    profile.parameters,
                    profile.memory.channel_capacity_bytes,
                    4,
                    4 * int(profile.parameters["regraph_partition_vertices"]),
                    4096,
                )
        catalog = load_capability_catalog(
            normalized_grasu_capability_catalog_path(ROOT, "k1_v4")
        )
        self.assertEqual(len(catalog.profiles), 9)
        for algorithm in ("weighted", "pagerank", "residual"):
            for k in (2, 4):
                profile = load_architecture_profile(
                    ROOT
                    / "configs"
                    / "architectures"
                    / f"grasu_regraph_candidate10_k{k}_multipart_{algorithm}_v4.json"
                )
                self.assertEqual(profile.parameters["regraph_compute_pipelines"], k)
                self.assertEqual(profile.evidence_tier, EvidenceTier.SIMULATION_ONLY)

    def test_residual_source_state_stride_rejects_three_partition_underflow(
        self,
    ) -> None:
        profile = load_architecture_profile(
            ROOT
            / "configs/architectures/grasu_regraph_candidate10_k1_multipart_residual_v4.json"
        )
        parameters = dict(profile.parameters)
        parameters["grasu_source_state_buffer_stride_bytes"] = 1 << 20
        with self.assertRaisesRegex(ValueError, "double-buffer stride is too small"):
            validate_grasu_hbm_address_map(
                parameters,
                profile.memory.channel_capacity_bytes,
                3,
                157_107,
                4096,
            )

    def test_v4_normalized_contract_is_publication_eligible_not_fpga_measured(
        self,
    ) -> None:
        validated = validate_normalized_profile_contract(
            ROOT / "configs/architectures/spine_candidate10_normalized_v1.json",
            normalized_grasu_profile_paths(ROOT, "k1_v4"),
        )
        self.assertEqual(validated["grasu_profile_set"], "k1_v4")
        feasibility = load_normalized_hls_feasibility(ROOT, FEASIBILITY)
        self.assertTrue(feasibility["all_matching_hls"])
        self.assertTrue(
            feasibility["claim_gates"]["headline_normalized_performance"][
                "eligible"
            ]
        )
        self.assertFalse(
            feasibility["claim_gates"]["iso_resource_performance"]["eligible"]
        )
        self.assertFalse(
            feasibility["claim_gates"]["fpga_measured_performance"]["eligible"]
        )


if __name__ == "__main__":
    unittest.main()
