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

    def _valid_result(self) -> dict[str, object]:
        params = self.profile["parameters"]
        supersteps = params["hls_validation_supersteps"]
        source_requests = 2 * supersteps
        source_lines = source_requests * params["regraph_source_buffer_vertices"] // 16
        rows = params["regraph_partition_vertices"] // 2 * supersteps
        bursts = params["regraph_partition_vertices"] // 16 * supersteps
        return {
            "success": True,
            "mode": "grasu_regraph_hls_weighted_sssp",
            "claim_class": "hls_sw_emu_aligned_execution_driven_simulation",
            "backend": "sst_memHierarchy_dramsim3",
            "pipeline_order": "update_then_barrier_then_pma_native_compute",
            "conversion_cost_included": False,
            "pma_edge_abi": params["grasu_pma_edge_abi"],
            "logical_updates": 5,
            "physical_updates": 8,
            "updates": 8,
            "update_inserts": 4,
            "update_deletes": 4,
            "update_weight_decreases": 0,
            "update_weight_increases": 0,
            "update_pma_reads": 8,
            "update_pma_writes": 8,
            "host_vertex_reorder": True,
            "external_to_internal": list(self.oracle.external_to_internal),
            "internal_to_external": list(self.oracle.internal_to_external),
            "source_external": 0,
            "source_internal": 0,
            "fixed_host_supersteps": True,
            "supersteps": supersteps,
            "correctness_mismatches": 0,
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "distances_external": list(self.oracle.external_distances),
            "edge_lanes": params["regraph_map_reduce_lanes"],
            "gather_banks": params["regraph_map_reduce_lanes"],
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


if __name__ == "__main__":
    unittest.main()
