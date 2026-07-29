from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.run_sst_grasu_regraph_hls_weighted import (
    HLS_INFINITY,
    build_hls_weighted_oracle,
    require_hls_weighted_capability,
    validate_result,
)
from spine_cycle_sim.experiments.profile_capabilities import ImplementationStatus
from spine_cycle_sim.experiments.shared_workloads import load_slice


ROOT = Path(__file__).resolve().parents[1]
PROFILE = (
    ROOT
    / "configs"
    / "architectures"
    / "grasu_regraph_weighted_pma_hls_sw_emu_ff13a67.json"
)
CATALOG = ROOT / "configs" / "contracts" / "grasu_regraph_capabilities_v1.json"
INITIAL = ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_initial.slice"
UPDATE = ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_update.slice"
MULTIPART_PROFILE = (
    ROOT
    / "configs"
    / "architectures"
    / "grasu_regraph_candidate10_k2_multipart_weighted_v4.json"
)
MULTIPART_INITIAL = (
    ROOT / "tests" / "data" / "grasu_regraph_partitioned_normalized_initial.slice"
)
MULTIPART_UPDATE = (
    ROOT / "tests" / "data" / "grasu_regraph_partitioned_normalized_update.slice"
)


class GrasuHlsWeightedRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.oracle = build_hls_weighted_oracle(
            load_slice(INITIAL), load_slice(UPDATE), 0
        )

    def test_independent_oracle_matches_sw_emu_fixture(self) -> None:
        self.assertEqual(self.oracle.logical_updates, 5)
        self.assertEqual(self.oracle.physical_updates, 8)
        self.assertEqual(
            self.oracle.external_to_internal, (0, 2, 1, 3, 4, 5, 6, 7)
        )
        self.assertEqual(
            self.oracle.external_distances,
            (0, 3, 10, 14, 12, HLS_INFINITY, HLS_INFINITY, HLS_INFINITY),
        )

    def test_capability_is_executable_and_conversion_free(self) -> None:
        catalog, capability = require_hls_weighted_capability(PROFILE, CATALOG)
        profile = catalog.profile(self.profile["profile_id"])
        self.assertEqual(capability.implementation_status, ImplementationStatus.EXECUTABLE)
        self.assertEqual(profile.handoff, "weighted_pma_to_axis_stream")
        self.assertEqual(profile.conversion_cost, "absent")

    def _valid_result(
        self,
        profile: dict[str, object] | None = None,
        oracle=None,
        supersteps: int | None = None,
    ) -> dict[str, object]:
        profile = self.profile if profile is None else profile
        oracle = self.oracle if oracle is None else oracle
        params = profile["parameters"]
        supersteps = (
            params["hls_validation_supersteps"]
            if supersteps is None
            else supersteps
        )
        partition_vertices = params["regraph_partition_vertices"]
        destination_partitions = (
            len(oracle.external_to_internal) + partition_vertices - 1
        ) // partition_vertices
        partition_max_sources: list[int | None] = [None] * destination_partitions
        for source, destination, _ in oracle.final_internal_edges:
            partition = destination // partition_vertices
            previous = partition_max_sources[partition]
            partition_max_sources[partition] = (
                source if previous is None else max(previous, source)
            )
        source_requests = sum(
            (source // params["regraph_source_buffer_vertices"] + 2) * supersteps
            for source in partition_max_sources
            if source is not None
        )
        source_lines = source_requests * params["regraph_source_buffer_vertices"] // 16
        rows = destination_partitions * partition_vertices // 2 * supersteps
        bursts = destination_partitions * partition_vertices // 16 * supersteps
        compute_pipelines = params.get("regraph_compute_pipelines", 1)
        downstream_sharing = params.get("regraph_downstream_sharing", "direct")
        return {
            "success": True,
            "mode": "grasu_regraph_hls_weighted_sssp",
            "claim_class": "hls_sw_emu_aligned_execution_driven_simulation",
            "backend": "sst_memHierarchy_dramsim3",
            "pipeline_order": "update_then_barrier_then_pma_native_compute",
            "conversion_cost_included": False,
            "pma_edge_abi": params["grasu_pma_edge_abi"],
            "logical_updates": oracle.logical_updates,
            "physical_updates": oracle.physical_updates,
            "updates": oracle.physical_updates,
            "update_inserts": 4,
            "update_deletes": 4,
            "update_weight_decreases": 0,
            "update_weight_increases": 0,
            "update_pma_reads": oracle.physical_updates,
            "update_pma_writes": oracle.physical_updates,
            "host_vertex_reorder": True,
            "external_to_internal": list(oracle.external_to_internal),
            "internal_to_external": list(oracle.internal_to_external),
            "source_external": 0,
            "source_internal": oracle.source_internal,
            "fixed_host_supersteps": True,
            "supersteps": supersteps,
            "correctness_mismatches": 0,
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "distances_external": list(oracle.external_distances),
            "edge_lanes": params["regraph_map_reduce_lanes"],
            "gather_banks": params["regraph_map_reduce_lanes"],
            "destination_partitions": destination_partitions,
            "compute_pipelines": compute_pipelines,
            "downstream_sharing": downstream_sharing,
            "max_parallel_downstream_partitions": (
                min(compute_pipelines, destination_partitions)
                if downstream_sharing == "direct"
                else 1
            ),
            "source_cache_requests": source_requests,
            "source_cache_lines": source_lines,
            "source_cache_lane_writes": source_lines
            * params["regraph_map_reduce_lanes"],
            "gather_rows_emitted": rows,
            "merger_rows_consumed": rows,
            "merger_bursts_emitted": bursts,
            "apply_input_bursts": bursts,
            "hbm_wrapper_input_bursts": bursts,
        }

    def test_result_validator_accepts_complete_contract(self) -> None:
        validate_result(self._valid_result(), self.profile, self.oracle)

    def test_result_validator_rejects_physical_update_drift(self) -> None:
        result = self._valid_result()
        result["physical_updates"] = 5
        with self.assertRaisesRegex(RuntimeError, "physical_updates"):
            validate_result(result, self.profile, self.oracle)

    def test_result_validator_accepts_two_partition_k2_contract(self) -> None:
        profile = json.loads(MULTIPART_PROFILE.read_text(encoding="utf-8"))
        oracle = build_hls_weighted_oracle(
            load_slice(MULTIPART_INITIAL), load_slice(MULTIPART_UPDATE), 0
        )
        result = self._valid_result(profile, oracle, supersteps=1)
        result["update_inserts"] = 4
        result["update_deletes"] = 2
        validate_result(result, profile, oracle, supersteps=1)
        self.assertEqual(result["destination_partitions"], 2)
        self.assertEqual(result["compute_pipelines"], 2)


if __name__ == "__main__":
    unittest.main()
