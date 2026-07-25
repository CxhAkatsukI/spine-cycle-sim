from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.regraph_contracts import (
    expected_pagerank_source_cache_requests,
)


class GraSuResidualRunnerTests(unittest.TestCase):
    def test_source_cache_prefetch_contract_at_4096_boundary(self) -> None:
        iterations = 74
        self.assertEqual(
            expected_pagerank_source_cache_requests(4095, 4096, iterations), 148
        )
        self.assertEqual(
            expected_pagerank_source_cache_requests(4096, 4096, iterations), 148
        )
        self.assertEqual(
            expected_pagerank_source_cache_requests(4097, 4096, iterations), 222
        )
        self.assertEqual(
            expected_pagerank_source_cache_requests(8192, 4096, iterations), 222
        )
        self.assertEqual(
            expected_pagerank_source_cache_requests(8193, 4096, iterations), 296
        )

    def test_source_cache_contract_rejects_nonpositive_dimensions(self) -> None:
        for arguments in ((0, 4096, 1), (1, 0, 1), (1, 4096, 0)):
            with self.assertRaisesRegex(ValueError, "must be positive"):
                expected_pagerank_source_cache_requests(*arguments)


if __name__ == "__main__":
    unittest.main()
