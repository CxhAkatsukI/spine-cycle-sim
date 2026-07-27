from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.temporal_real_analysis import _group_summaries


class TemporalRealAnalysisTest(unittest.TestCase):
    def test_group_summary_uses_geometric_speedups(self) -> None:
        rows = []
        for dataset, scenario, speedup in (
            ("a", "insert", 0.25),
            ("a", "delete", 1.0),
            ("b", "insert", 4.0),
        ):
            rows.append(
                {
                    "dataset_id": dataset,
                    "scenario": scenario,
                    "spine_e2e_ms": 4.0,
                    "grasu_e2e_ms": 4.0 * speedup,
                    "spine_speedup_over_grasu_e2e": speedup,
                    "spine_speedup_over_grasu_update": speedup,
                    "spine_speedup_over_grasu_compute": speedup,
                    "grasu_to_spine_backend_request_ratio": 2.0,
                    "grasu_to_spine_backend_byte_ratio": 3.0,
                    "spine_dram_row_hit_rate": 0.5,
                    "grasu_dram_row_hit_rate": 0.75,
                    "spine_dram_average_read_latency": 20.0,
                    "grasu_dram_average_read_latency": 30.0,
                }
            )
        summaries = _group_summaries(rows)
        overall = summaries[0]
        self.assertAlmostEqual(overall["spine_speedup_e2e_geomean"], 1.0)
        self.assertEqual(overall["spine_wins"], 1)
        self.assertEqual(len(summaries), 1 + 2 + 2)


if __name__ == "__main__":
    unittest.main()
