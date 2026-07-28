from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.deltahls_workloads import (
    balanced_partition_scalability_fixture,
    reciprocal_closure,
    reciprocal_insert_batches,
    validate_reciprocal_graph,
    validate_reciprocal_update,
)
from spine_cycle_sim.experiments.shared_workloads import SliceGraph, SliceRecord


class DeltaHlsWorkloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directed = SliceGraph(
            "directed",
            5,
            (
                SliceRecord(0, 1, 3, 1),
                SliceRecord(0, 2, 5, 1),
                SliceRecord(3, 0, 7, 1),
                SliceRecord(4, 3, 11, 1),
            ),
        )

    def test_reciprocal_closure_is_sink_free_and_weight_preserving(self) -> None:
        closure = reciprocal_closure(self.directed, case_id="closed")
        validate_reciprocal_graph(closure.graph)
        self.assertEqual(closure.original_records, 4)
        self.assertEqual(closure.reciprocal_records_added, 4)
        self.assertEqual(len(closure.graph.records), 8)
        edges = {(edge.src, edge.dst): edge.weight for edge in closure.graph.records}
        self.assertEqual(edges[(1, 0)], 3)
        self.assertEqual(edges[(0, 1)], 3)

    def test_batches_are_deterministic_nested_atomic_pairs(self) -> None:
        graph = reciprocal_closure(self.directed, case_id="closed").graph
        first = reciprocal_insert_batches(graph, (1, 3), case_prefix="unit", seed=7)
        second = reciprocal_insert_batches(graph, (1, 3), case_prefix="unit", seed=7)
        self.assertEqual(first, second)
        self.assertEqual(len(first[1].records), 2)
        self.assertEqual(len(first[3].records), 6)
        self.assertTrue(set(first[1].records).issubset(first[3].records))
        validate_reciprocal_update(graph, first[3])

    def test_closure_rejects_isolated_vertices(self) -> None:
        graph = SliceGraph("isolated", 3, (SliceRecord(0, 1, 1, 1),))
        with self.assertRaisesRegex(ValueError, "isolated"):
            reciprocal_closure(graph, case_id="bad")

    def test_update_validator_rejects_one_sided_record(self) -> None:
        graph = reciprocal_closure(self.directed, case_id="closed").graph
        update = SliceGraph("bad", graph.vertices, (SliceRecord(1, 4, 1, 1),))
        with self.assertRaisesRegex(ValueError, "atomic reciprocal"):
            validate_reciprocal_update(graph, update)

    def test_balanced_scalability_fixture_touches_every_partition(self) -> None:
        fixture = balanced_partition_scalability_fixture(
            partition_vertices=8, partitions=4
        )
        self.assertEqual(fixture.graph.vertices, 32)
        self.assertEqual(len(fixture.graph.records), 32)
        self.assertEqual(len(fixture.update.records), 8)
        touched = {
            record.dst // fixture.partition_vertices
            for record in fixture.update.records
        }
        self.assertEqual(touched, {0, 1, 2, 3})
        validate_reciprocal_graph(fixture.graph)
        validate_reciprocal_update(fixture.graph, fixture.update)

    def test_balanced_scalability_fixture_rejects_odd_partition_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "even"):
            balanced_partition_scalability_fixture(
                partition_vertices=7, partitions=4
            )


if __name__ == "__main__":
    unittest.main()
