from __future__ import annotations

import unittest

from scripts.run_sst_grasu_regraph_pagerank import (
    full_pagerank_rank_sum_tolerance,
)


class FullPageRankRunnerContractTest(unittest.TestCase):
    def test_rank_sum_bound_accumulates_per_vertex_float32_error(self) -> None:
        error = 3.13462e-9
        tolerance = full_pagerank_rank_sum_tolerance(8191, error)

        self.assertAlmostEqual(tolerance, 1.0e-5 + 8191 * error)
        self.assertGreaterEqual(tolerance, abs(0.99997 - 1.0))

    def test_rank_sum_bound_preserves_small_graph_floor(self) -> None:
        self.assertEqual(full_pagerank_rank_sum_tolerance(4, 0.0), 1.0e-5)

    def test_rank_sum_bound_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            full_pagerank_rank_sum_tolerance(0, 0.0)
        with self.assertRaises(ValueError):
            full_pagerank_rank_sum_tolerance(1, -1.0)


if __name__ == "__main__":
    unittest.main()
