import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.shard_layout import (
    slot_counts,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.shard_windows import (
    publication_windows,
)


class PublicationWindowsTest(unittest.TestCase):
    def test_layout_remaps_nonempty_sources_and_keeps_leading_guard(self):
        self.assertEqual(slot_counts([0, 0, 1, 1, 2], [0, 1], 2), ([1, 1], [32, 16]))
        self.assertEqual(slot_counts([0, 0, 0], [], 1), ([0, 0], [16, 16]))
        with self.assertRaisesRegex(ValueError, "unique"):
            slot_counts([0, 2, 2], [1, 1], 1)

    def test_preserves_envelope_and_does_not_add_overlapping_frontends(self):
        config = {"shards": 5, "pma_slots": 320, "edges": 100}
        intervals = [(10, 100), (11, 99)] + [
            (11 + s, 46 + s) if role == 0 else (12 + s, 53 + s) if role == 1
            else (20 + 10 * s, 28 + 10 * s)
            for s in range(5) for role in range(3)
        ]
        events = [{"ordinal": i, "start_ns": a, "end_ns": b}
                  for i, (a, b) in enumerate(intervals)]
        result = publication_windows(config, events, 90)
        self.assertEqual(result["mux_span_by_worker_ns"], [16, 8, 8, 8])
        self.assertEqual(result["fraction_of_elapsed_by_worker"][0], 16 / 90)
        self.assertEqual(result["windows"][4]["mux_start_ns"], 50)
        events[7]["start_ns"] = 25
        with self.assertRaisesRegex(ValueError, "ordered publication"):
            publication_windows(config, events, 90)
