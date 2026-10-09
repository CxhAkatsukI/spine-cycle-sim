from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.run_sst_grasu_regraph_native import (
    DEFAULT_CAPABILITY_CATALOG,
    native_active_hbm_channels,
    require_native_algorithm_capability,
    validate_result,
)
from spine_cycle_sim.experiments import grasu_native_validation


ROOT = Path(__file__).resolve().parents[1]
PROFILE = (
    ROOT / "configs" / "architectures" / "grasu_regraph_native_a9aef06.json"
)


class GraSuNativeRunnerTests(unittest.TestCase):
    def test_cli_reexports_canonical_validation_without_a_second_copy(self) -> None:
        self.assertIs(validate_result, grasu_native_validation.validate_result)
        self.assertIs(
            native_active_hbm_channels,
            grasu_native_validation.native_active_hbm_channels,
        )
        self.assertIs(
            require_native_algorithm_capability,
            grasu_native_validation.require_native_algorithm_capability,
        )

    def setUp(self) -> None:
        self.profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.result = {
            "success": True,
            "mode": "grasu_regraph_native_sssp",
            "claim_class": "native_structural_simulation",
            "backend": "sst_memHierarchy_dramsim3",
            "conversion_cost_included": True,
            "native_host_vertex_reorder": True,
            "source": 0,
            "source_external": 0,
            "source_internal": 0,
            "pipeline_order": "update_then_barrier_compactor_then_compute",
            "cycles": 100,
            "component_cycles": 100,
            "controller_gap_cycles": 0,
            "correctness_mismatches": 0,
            "native_hls_contract_safe": True,
            "cross_source_round_bursts": 0,
            "pma_edge_abi": "native_raw_destination32",
            "supersteps": 2,
            "completion_token_reads": 4,
            "barrier_cycles": 4,
            "vertices": 16,
            "compactor_row_reads": 17,
            "pma_slots": 48,
            "compactor_pma_slots_scanned": 48,
            "final_edges": 3,
            "compact_edge_slots": 32,
            "compactor_valid_edges": 3,
            "compactor_dummy_edge_slots": 29,
            "compactor_edge_array_writes": 4,
            "edge_array_requests": 2,
            "edge_array_bursts": 8,
            "edge_array_slots_scanned": 64,
            "edge_array_read_bytes": 512,
            "apply_state_reads": 8192,
            "apply_state_writes": 8192,
            "compute_source_state_writes": 16384,
        }

    def test_accepts_closed_safe_native_ledger(self) -> None:
        validate_result(self.result, self.profile, 0)

    def test_native_runner_is_bound_to_executable_unit_sssp_capability(self) -> None:
        catalog, capability = require_native_algorithm_capability(
            PROFILE.resolve(), DEFAULT_CAPABILITY_CATALOG.resolve()
        )
        self.assertEqual(capability.algorithm, "unit_weight_sssp")
        self.assertEqual(capability.evidence_tier, "hardware_validated")
        self.assertEqual(
            catalog.profile(self.profile["profile_id"]).conversion_cost,
            "included",
        )

    def test_derives_only_hls_reachable_hbm_channels(self) -> None:
        self.assertEqual(
            native_active_hbm_channels(self.profile), (0, 1, 2, 3, 30)
        )

    def test_rejects_out_of_range_hls_channel(self) -> None:
        invalid = json.loads(json.dumps(self.profile))
        invalid["parameters"]["regraph_vertex_prop_hbm_channel"] = 32
        with self.assertRaisesRegex(ValueError, "out-of-range"):
            native_active_hbm_channels(invalid)

    def test_rejects_hidden_conversion_or_cross_window_burst(self) -> None:
        for field, value in (
            ("conversion_cost_included", False),
            ("cross_source_round_bursts", 1),
            ("native_hls_contract_safe", False),
            ("correctness_mismatches", 1),
            ("native_host_vertex_reorder", False),
        ):
            with self.subTest(field=field):
                invalid = dict(self.result)
                invalid[field] = value
                with self.assertRaises(RuntimeError):
                    validate_result(invalid, self.profile)

    def test_rejects_wrong_external_source_or_internal_alias(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_result(self.result, self.profile, 7)
        invalid = dict(self.result)
        invalid["source"] = 1
        with self.assertRaises(RuntimeError):
            validate_result(invalid, self.profile, 0)


if __name__ == "__main__":
    unittest.main()
