import unittest

from scripts.freeze_current_fpga_spine_realized_work_v13 import work_counters


class CurrentFPGASpineRealizedWorkV13Tests(unittest.TestCase):
    def test_sssp_work_counters_use_routed_round_ledgers(self) -> None:
        self.assertEqual(
            work_counters(
                "weighted_sssp",
                {
                    "rounds": 2,
                    "reader_range_tasks_per_round": [19, 1],
                    "processed_edges_per_round": [20, 1],
                },
            ),
            (2, 20.0, 21.0),
        )

    def test_cc_work_counters_use_iteration_ledgers(self) -> None:
        self.assertEqual(
            work_counters(
                "connected_components",
                {
                    "iterations": 2,
                    "reader_range_tasks_per_iteration": [15, 7],
                    "reader_edges_per_iteration": [1979, 7],
                },
            ),
            (2, 22.0, 1986.0),
        )

    def test_residual_has_no_iterative_work_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "no iterative"):
            work_counters("thresholded_residual_pagerank", {})


if __name__ == "__main__":
    unittest.main()
