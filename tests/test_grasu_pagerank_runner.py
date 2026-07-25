from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.regraph_contracts import (
    float32_sequential_rank_sum_tolerance,
    full_pagerank_rank_sum_tolerance,
)


class FullPageRankRunnerContractTest(unittest.TestCase):
    def test_rank_sum_bound_accumulates_per_vertex_float32_error(self) -> None:
        error = 3.13462e-9
        tolerance = full_pagerank_rank_sum_tolerance(8191, error)

        self.assertAlmostEqual(tolerance, 1.0e-5 + 8191 * error)
        self.assertGreaterEqual(tolerance, abs(0.99997 - 1.0))

    def test_reported_float32_sum_gets_a_separate_roundoff_bound(self) -> None:
        accurate = full_pagerank_rank_sum_tolerance(8193, 7.92032e-10)
        reported = float32_sequential_rank_sum_tolerance(8193, accurate)

        self.assertLess(accurate, abs(0.999913 - 1.0))
        self.assertGreaterEqual(reported, abs(0.999913 - 1.0))

    def test_rank_sum_bound_preserves_small_graph_floor(self) -> None:
        self.assertEqual(full_pagerank_rank_sum_tolerance(4, 0.0), 1.0e-5)

    def test_rank_sum_bound_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            full_pagerank_rank_sum_tolerance(0, 0.0)
        with self.assertRaises(ValueError):
            full_pagerank_rank_sum_tolerance(1, -1.0)


if __name__ == "__main__":
    unittest.main()
