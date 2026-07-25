from __future__ import annotations

import unittest

from scripts.run_grasu_hls_weighted_matrix import _select_fixtures
from scripts.run_sst_grasu_regraph_hls_weighted import (
    HLS_INFINITY,
    build_hls_weighted_oracle,
)
from spine_cycle_sim.experiments.hls_weighted_workloads import (
    hls_weighted_fixtures,
)


class GrasuHlsWeightedMatrixTests(unittest.TestCase):
    def test_frozen_matrix_covers_ten_disjoint_gap_families(self) -> None:
        fixtures = hls_weighted_fixtures()
        self.assertEqual(len(fixtures), 10)
        self.assertEqual(len({fixture.fixture_id for fixture in fixtures}), 10)
        self.assertEqual(len({fixture.family for fixture in fixtures}), 10)
        self.assertEqual(
            {fixture.role for fixture in fixtures}, {"calibration", "holdout"}
        )

    def test_physical_lowering_counts_are_frozen(self) -> None:
        expected = {
            "hls_insert_shortcut_v8": 1,
            "hls_exact_delete_v8": 1,
            "hls_weight_decrease_v8": 2,
            "hls_weight_increase_v8": 2,
            "hls_mixed_update_v8": 8,
            "hls_chain_exact_four_hops_v8": 2,
            "hls_dense_fanin_v64": 28,
            "hls_source_window_4096_v8194": 2,
            "hls_multisegment_variants_v128": 34,
            "hls_reorder_tie_v8": 6,
        }
        for fixture in hls_weighted_fixtures():
            with self.subTest(case=fixture.fixture_id):
                oracle = build_hls_weighted_oracle(
                    fixture.graph, fixture.update, fixture.source
                )
                self.assertEqual(oracle.physical_updates, expected[fixture.fixture_id])
                self.assertEqual(oracle.logical_updates, len(fixture.update.records))

    def test_every_correctness_case_converges_within_four_rounds(self) -> None:
        for fixture in hls_weighted_fixtures():
            with self.subTest(case=fixture.fixture_id):
                oracle = build_hls_weighted_oracle(
                    fixture.graph, fixture.update, fixture.source
                )
                distances = [HLS_INFINITY] * fixture.graph.vertices
                distances[fixture.source] = 0
                for _ in range(4):
                    next_distances = distances.copy()
                    for source, destination, weight in oracle.final_external_edges:
                        if distances[source] != HLS_INFINITY:
                            next_distances[destination] = min(
                                next_distances[destination],
                                distances[source] + weight,
                            )
                    distances = next_distances
                self.assertEqual(tuple(distances), oracle.external_distances)

    def test_source_window_and_reorder_tie_boundaries_are_exact(self) -> None:
        fixtures = {fixture.fixture_id: fixture for fixture in hls_weighted_fixtures()}
        source_window = build_hls_weighted_oracle(
            fixtures["hls_source_window_4096_v8194"].graph,
            fixtures["hls_source_window_4096_v8194"].update,
            0,
        )
        self.assertEqual(max(src for src, _, _ in source_window.final_internal_edges), 4096)
        tie = build_hls_weighted_oracle(
            fixtures["hls_reorder_tie_v8"].graph,
            fixtures["hls_reorder_tie_v8"].update,
            0,
        )
        self.assertEqual(tie.internal_to_external[:3], (0, 1, 2))

    def test_selection_is_fail_closed(self) -> None:
        fixtures = hls_weighted_fixtures()
        selected = _select_fixtures(fixtures, [], ["holdout"], 2)
        self.assertEqual(len(selected), 2)
        self.assertTrue(all(fixture.role == "holdout" for fixture in selected))
        with self.assertRaisesRegex(ValueError, "unknown"):
            _select_fixtures(fixtures, ["not-a-case"], [], None)


if __name__ == "__main__":
    unittest.main()
