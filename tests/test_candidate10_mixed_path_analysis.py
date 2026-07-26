from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.mixed_path_analysis import analyze_mixed_path


class Candidate10MixedPathAnalysisTests(unittest.TestCase):
    @staticmethod
    def _spine() -> dict[str, object]:
        return {
            "success": True,
            "input_edges": 8_193,
            "cycles": 417_427,
            "round_cycles": [408_687, 8_141],
            "round_post_maintenance_cycles": [112_494, 8_141],
            "dirty_ack_cycles": 598,
            "fast_tiles_per_round": [1, 0],
            "full_tiles_per_round": [1, 0],
            "reader_range_fallback_reasons_per_round": [0, 0],
            "reader_range_tasks_per_round": [2, 0],
            "reader_range_construction_payloads_per_round": [8_193, 0],
            "reader_range_replay_payloads_per_round": [8_193, 0],
        }

    @staticmethod
    def _maintenance() -> dict[str, object]:
        return {
            "success": True,
            "maintenance_cycles": 296_193,
            "maintenance_launch_to_first_memory_issue_cycles": 1,
            "maintenance_memory_active_span_cycles": 296_191,
            "maintenance_post_memory_drain_cycles": 1,
            "maintenance_memory_ledger_closed": True,
            "backend_arbitration": {"ledger_closed": True, "contended_cycles": 0},
        }

    @staticmethod
    def _hardware() -> dict[str, str]:
        return {
            "input_edges": "8193",
            "fast_path_tiles": "1",
            "full_path_tiles": "1",
            "fallback_used": "0",
            "task_count": "2",
            "task_construction_payloads": "8193",
            "task_replay_payloads": "8193",
            "maint_ms": "3.20251",
            "conv_ms": "7.3803",
            "kernel_e2e_ms": "10.5828",
        }

    def test_mixed_path_schedule_and_phase_ledgers_close(self) -> None:
        result = analyze_mixed_path(self._spine(), self._maintenance(), self._hardware())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["path_class"], "mixed_fast_full_no_fallback")
        self.assertEqual(result["simulator_timing"]["first_d_core_span_cycles"], 112_494)
        self.assertEqual(result["simulator_timing"]["scheduler_boundary_cycles"], 1)
        self.assertFalse(result["diagnostic_differences"]["scope_matched"])

    def test_rejects_fallback_or_open_ledgers(self) -> None:
        spine = self._spine()
        spine["reader_range_fallback_reasons_per_round"] = [2, 0]
        with self.assertRaisesRegex(ValueError, "simulator mixed schedule"):
            analyze_mixed_path(spine, self._maintenance(), self._hardware())

        maintenance = self._maintenance()
        maintenance["maintenance_post_memory_drain_cycles"] = 2
        with self.assertRaisesRegex(ValueError, "B phase ledger"):
            analyze_mixed_path(self._spine(), maintenance, self._hardware())


if __name__ == "__main__":
    unittest.main()
