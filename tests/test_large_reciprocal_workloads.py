from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.connected_components_workloads import (
    analyze_reciprocal_update,
    connected_components_labels,
    materialize_reciprocal_update,
)
from spine_cycle_sim.experiments.large_reciprocal_workloads import (
    component_bridge_batches,
    ordered_reciprocal_projection,
)
from spine_cycle_sim.experiments.shared_workloads import SliceGraph, SliceRecord


class LargeReciprocalWorkloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = SliceGraph(
            "source",
            12,
            (
                SliceRecord(7, 1),
                SliceRecord(1, 7),
                SliceRecord(4, 2),
                SliceRecord(9, 10),
                SliceRecord(5, 6),
                SliceRecord(8, 11),
            ),
        )

    def test_projection_is_compact_reciprocal_and_sink_free(self) -> None:
        graph, scanned = ordered_reciprocal_projection(
            self.source, target_records=8, case_id="projection"
        )
        self.assertEqual(scanned, 5)
        self.assertEqual(graph.vertices, 8)
        self.assertEqual(len(graph.records), 8)
        self.assertEqual(len(connected_components_labels(graph)), 8)

    def test_component_bridge_batches_are_nested_and_merge_components(self) -> None:
        graph, _ = ordered_reciprocal_projection(
            self.source, target_records=8, case_id="projection"
        )
        batches = component_bridge_batches(
            graph, (1, 2), case_prefix="projection"
        )
        self.assertEqual(len(batches[1].records), 2)
        self.assertEqual(len(batches[2].records), 4)
        self.assertTrue(set(batches[1].records) < set(batches[2].records))
        initial_components = len(set(connected_components_labels(graph)))
        for size, update in batches.items():
            analysis = analyze_reciprocal_update(graph, update)
            final = materialize_reciprocal_update(graph, update)
            self.assertEqual(analysis.effective_mutations, size)
            self.assertEqual(
                len(set(connected_components_labels(final))),
                initial_components - size,
            )


if __name__ == "__main__":
    unittest.main()
