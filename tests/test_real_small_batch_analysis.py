from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.real_small_batch_analysis import (
    build_pair_rows,
    normalize_system_row,
    summarize_pairs,
)


class RealSmallBatchAnalysisTests(unittest.TestCase):
    @staticmethod
    def _row(system: str, e2e_ms: float, update_ms: float) -> dict[str, object]:
        return {
            "run_id": "real_test_insert_u8",
            "dataset_id": "test",
            "scenario": "insert",
            "system": system,
            "profile_id": system,
            "core_mhz": 150.0,
            "vertices": 64,
            "initial_edges": 128,
            "user_mutations": 8,
            "physical_records": 8,
            "e2e_ms": e2e_ms,
            "update_ms": update_ms,
            "backend_requests": 100 if system == "spine" else 200,
            "backend_bytes": 3_200 if system == "spine" else 6_400,
            "backend_discontinuous_request_ratio": 0.25,
            "correctness_mismatches": 0,
        }

    def test_normalizes_pagerank_update_throughput(self) -> None:
        row = normalize_system_row(self._row("spine", 4.0, 1.0), "full_pagerank")
        self.assertEqual(row["compute_ms"], 3.0)
        self.assertEqual(row["user_mutations_per_second_update"], 8_000.0)

    def test_pairs_and_summarizes_common_timing_windows(self) -> None:
        rows = [
            normalize_system_row(self._row("spine", 4.0, 1.0), "full_pagerank"),
            normalize_system_row(
                self._row("grasu_regraph", 8.0, 0.5), "full_pagerank"
            ),
        ]
        pairs = build_pair_rows(rows)
        self.assertEqual(pairs[0]["spine_speedup_over_grasu_e2e"], 2.0)
        self.assertEqual(pairs[0]["spine_speedup_over_grasu_update"], 0.5)
        self.assertEqual(pairs[0]["grasu_to_spine_backend_request_ratio"], 2.0)
        summary = summarize_pairs(pairs)[0]
        self.assertEqual(summary["spine_e2e_wins"], 1)
        self.assertEqual(summary["spine_speedup_over_grasu_e2e_geomean"], 2.0)

    def test_weighted_window_uses_structure_cycles(self) -> None:
        row = {
            **self._row("spine", 0.0, 0.0),
            "aligned_e2e_ms": 4.0,
            "structure_update_cycles": 150,
            "aligned_backend_requests": 50,
            "aligned_backend_bytes": 1_600,
        }
        normalized = normalize_system_row(row, "weighted_sssp")
        self.assertEqual(normalized["update_ms"], 0.001)
        self.assertEqual(normalized["compute_ms"], 3.999)


if __name__ == "__main__":
    unittest.main()
