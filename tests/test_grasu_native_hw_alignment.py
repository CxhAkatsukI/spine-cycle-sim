from __future__ import annotations

import unittest

from scripts.analyze_grasu_native_hw_alignment import analyze, parse_hardware_log


HARDWARE_LOG = """\
PURE_PIPELINE_INPUT vertices=4 static_edges=2 update_edges=1 final_edges=3 pma_slots=32 compact_edge_slots=8 source_external=0 source_internal=0 supersteps=2
PURE_PIPELINE_SUPERSTEP step=1 lksg_ms=0.2 apply_ms=0.3 hbm_ms=0.4
PURE_PIPELINE_SUPERSTEP step=2 lksg_ms=0.1 apply_ms=0.2 hbm_ms=0.3
PURE_PIPELINE_TIMING grasu_ms=1.0 barrier_ms=0.1 adapter_ms=1.9 pma_compact_ms=1.9 lksg_ms=0.3 apply_ms=0.5 hbm_ms=0.7 event_e2e_ms=4.0 wall_ms=4.2
PURE_PIPELINE_RESULT status=PASS mismatches=0 vertices=4 final_edges=3 pma_scan_slots_once=32 processed_edge_slots_per_superstep=8 source_external=0 source_internal=0 supersteps=2
"""


def simulation_result() -> dict[str, object]:
    return {
        "success": True,
        "mode": "grasu_regraph_native_sssp",
        "cycles": 800_000,
        "update_cycles": 200_000,
        "conversion_cycles": 400_000,
        "compute_cycles": 200_000,
        "vertices": 4,
        "source": 0,
        "source_external": 0,
        "source_internal": 0,
        "native_host_vertex_reorder": True,
        "initial_edges": 2,
        "updates": 1,
        "final_edges": 3,
        "pma_slots": 32,
        "compact_edge_slots": 8,
        "supersteps": 2,
        "compactor_pma_slots_scanned": 32,
        "edge_array_slots_scanned": 16,
        "correctness_mismatches": 0,
    }


class GraSuNativeHardwareAlignmentTests(unittest.TestCase):
    def test_parses_and_matches_closed_native_ledger(self) -> None:
        hardware = parse_hardware_log(HARDWARE_LOG)
        report = analyze(simulation_result(), hardware, 200.0)
        self.assertTrue(report["structure_matches"])
        self.assertEqual(report["structural_claim"], "hardware_aligned")
        self.assertEqual(report["timing_claim"], "trend_only_not_cycle_calibrated")
        self.assertAlmostEqual(report["timing"]["event_e2e"]["simulation_ms"], 4.0)
        self.assertAlmostEqual(report["timing"]["conversion"]["hardware_ms"], 2.0)

    def test_reports_structural_mismatch_separately_from_timing(self) -> None:
        result = simulation_result()
        result["pma_slots"] = 48
        report = analyze(result, parse_hardware_log(HARDWARE_LOG), 200.0)
        self.assertFalse(report["structure_matches"])
        self.assertFalse(report["structural_checks"]["pma_slots"]["match"])

    def test_rejects_incomplete_or_failed_hardware_log(self) -> None:
        with self.assertRaises(ValueError):
            parse_hardware_log("PURE_PIPELINE_RESULT status=FAIL mismatches=1\n")


if __name__ == "__main__":
    unittest.main()
