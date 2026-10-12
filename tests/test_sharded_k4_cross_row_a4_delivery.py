"""Recheck portable actual-layout controls and reject altered raw evidence."""

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_archive import extracted
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.a4_control.delivery import verify, watchdog
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.a4_control.recheck import recheck

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / ("docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/"
              "adapter_optimization/row_line/cross_row/a4_control/evidence")


class CrossRowA4DeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        record = json.loads((DOC / "verification.json").read_text())
        cls.context = extracted(DOC / "raw_cross_row_A4.tar.gz", record, max_bytes=512 * 1024**2)
        cls.evidence_root = cls.context.__enter__()
        cls.addClassCleanup(cls.context.__exit__, None, None, None)

    def reject(self, relative, mutate, pattern):
        path = self.evidence_root / "run" / relative
        original = path.read_bytes()
        try:
            path.write_bytes(mutate(original))
            with self.assertRaisesRegex(ValueError, pattern):
                recheck(self.evidence_root / "run")
        finally:
            path.write_bytes(original)

    def test_portable_matrix_retains_negative_finding_and_scope(self):
        result = verify(DOC)
        self.assertEqual(len(result["cases"]), 18)
        self.assertTrue(result["admission"]["exact_whole_line_replay"])
        self.assertTrue(result["admission"]["cross_row_full_state_and_traffic"])
        for key in ("hardware_timing_admitted", "strict_resource_match_admitted",
                    "publication_match_admitted", "convergence_comparison"):
            self.assertFalse(result["admission"][key])
        candidates = [c for c in result["cases"] if c["arm"] == "cross_row"]
        self.assertEqual([c["counters"]["cycles"] for c in candidates],
                         [5310204, 5310204, 5310204, 5310204, 9382727, 9382727])
        self.assertTrue(all(c["k4_over_A4_cycles_diagnostic_only"] > 7 for c in candidates))

    def test_changed_reference_cycle_rejected(self):
        def mutate(data):
            lines = data.decode().splitlines()
            row = json.loads(lines[1].removeprefix("REAL_ROUND "))
            row["cycles"] += 1
            lines[1] = "REAL_ROUND " + json.dumps(row)
            return ("\n".join(lines) + "\n").encode()
        self.reject("raw/cold_lat64_reverse0_whole_line.stdout.txt", mutate, "reference replay")

    def test_changed_candidate_traffic_rejected(self):
        def mutate(data):
            lines = data.decode().splitlines()
            row = json.loads(lines[1].removeprefix("REAL_ROUND "))
            row["row_reads"] -= 1
            lines[1] = "REAL_ROUND " + json.dumps(row)
            return ("\n".join(lines) + "\n").encode()
        self.reject("raw/cold_lat64_reverse0_cross_row.stdout.txt", mutate, "conserved traffic")

    def test_complete_state_mutation_rejected(self):
        self.reject("states/cold_lat64_reverse0_cross_row/k4_source1.u32le",
                    lambda data: bytes([data[0] ^ 1]) + data[1:], "oracle")

    def test_executed_source_mutation_rejected(self):
        self.reject("sources/cpp/tests/routed_regraph/round_execution.hpp",
                    lambda data: data + b"\n", "executed source")

    def test_sealed_summary_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary)
            (copy / "verification.json").write_bytes((DOC / "verification.json").read_bytes())
            (copy / "results.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "sealed summary"):
                verify(copy)

    def test_aggregate_watchdog_keeps_memory_and_completion_gates(self):
        record = watchdog(self.evidence_root / "run", self.evidence_root / "watchdog/resources.json")
        self.assertEqual((record["exit_code"], record["stop_reason"]), (0, "process_exit"))
        self.assertEqual((record["tree_memory_gib"], record["reserve_gib"]), (8, 16))
        self.assertGreaterEqual(record["minimum_available_bytes"], 16 * 1024**3)


if __name__ == "__main__":
    unittest.main()
