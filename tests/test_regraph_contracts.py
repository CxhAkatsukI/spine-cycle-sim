from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.regraph_contracts import (
    expected_weighted_source_cache_requests,
    materialized_max_source,
)


class ReGraphWeightedContractsTest(unittest.TestCase):
    def test_weighted_prefetch_depends_on_highest_live_source_window(self) -> None:
        self.assertEqual(expected_weighted_source_cache_requests(0, 4096, 2), 4)
        self.assertEqual(expected_weighted_source_cache_requests(4095, 4096, 2), 4)
        self.assertEqual(expected_weighted_source_cache_requests(4096, 4096, 2), 6)
        self.assertEqual(expected_weighted_source_cache_requests(8192, 4096, 2), 8)

    def test_materialization_tracks_insert_delete_and_weight_change(self) -> None:
        initial = [(0, 1, 4, 1), (4096, 2, 8, 1)]
        update = [(4096, 2, 8, -1), (8192, 3, 5, 1)]
        self.assertEqual(materialized_max_source(initial, update), 8192)

        weight_change = [(8192, 3, 5, -1), (0, 1, 2, 1)]
        self.assertEqual(
            materialized_max_source((*initial, *update), weight_change), 0
        )

    def test_materialization_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            materialized_max_source([(0, 1, 1, 1)], [(2, 3, 1, -1)])
        with self.assertRaises(ValueError):
            materialized_max_source([(0, 1, 1, 1)], [(0, 1, 1, -1)])


if __name__ == "__main__":
    unittest.main()
