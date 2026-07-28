from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.connected_components_workloads import (
    analyze_reciprocal_update,
    connected_components_labels,
    formal_connected_components_fixtures,
    materialize_reciprocal_update,
)
from spine_cycle_sim.experiments.shared_workloads import SliceGraph, SliceRecord


class ConnectedComponentsWorkloadTests(unittest.TestCase):
    def test_formal_matrix_covers_frozen_classes_and_batch_sizes(self) -> None:
        fixtures = formal_connected_components_fixtures()
        classes = {fixture.workload_class for fixture in fixtures}
        self.assertTrue(
            {
                "same_component_noop",
                "small_component_merge",
                "small_to_large_merge",
                "large_component_merge",
                "hub_bridge",
                "zero_net_no_analytic_version",
                "dense_nested_component_merge",
                "reciprocal_deletion_full_recompute",
            }.issubset(classes)
        )
        ids = {fixture.fixture_id for fixture in fixtures}
        for size in (1, 8, 64, 4096):
            self.assertIn(f"cc_pair_bank_insert_u{size}", ids)
        self.assertIn("cc_deletion_chain_delete_u8", ids)
        self.assertIn("cc_deletion_chain_delete_u64", ids)

    def test_every_fixture_is_reciprocal_and_matches_bfs(self) -> None:
        for fixture in formal_connected_components_fixtures():
            with self.subTest(fixture=fixture.fixture_id):
                analysis = analyze_reciprocal_update(fixture.graph, fixture.update)
                final = materialize_reciprocal_update(fixture.graph, fixture.update)
                labels = connected_components_labels(final)
                self.assertEqual(analysis.physical_records, 2 * analysis.logical_user_mutations)
                self.assertEqual(len(labels), final.vertices)
                self.assertTrue(all(0 <= label < final.vertices for label in labels))
                if fixture.workload_class == "zero_net_no_analytic_version":
                    self.assertTrue(analysis.zero_net)
                    self.assertEqual(fixture.graph.records, final.records)

    def test_pair_bank_batches_are_nested_and_dense_batch_is_4096(self) -> None:
        fixtures = {
            fixture.fixture_id: fixture
            for fixture in formal_connected_components_fixtures()
            if fixture.fixture_id.startswith("cc_pair_bank_insert_u")
        }
        records = [
            set(fixtures[f"cc_pair_bank_insert_u{size}"].update.records)
            for size in (1, 8, 64, 4096)
        ]
        self.assertTrue(records[0] < records[1] < records[2] < records[3])
        self.assertEqual(len(records[-1]), 8192)

    def test_one_sided_update_is_rejected(self) -> None:
        graph = SliceGraph(
            "base",
            4,
            (SliceRecord(0, 1, 1, 1), SliceRecord(1, 0, 1, 1)),
        )
        update = SliceGraph("bad", 4, (SliceRecord(1, 2, 1, 1),))
        with self.assertRaisesRegex(ValueError, "atomic reciprocal"):
            analyze_reciprocal_update(graph, update)


if __name__ == "__main__":
    unittest.main()
