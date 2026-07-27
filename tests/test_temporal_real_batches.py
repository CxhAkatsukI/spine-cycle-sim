from __future__ import annotations

import gzip
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.temporal_real_batches import (
    TemporalSourceSpec,
    build_temporal_update,
    extract_temporal_compact_slice,
)
from spine_cycle_sim.experiments.real_small_batches import apply_explicit_weighted_updates


class TemporalRealBatchesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "events.txt.gz"
        with gzip.open(self.path, "wt", encoding="ascii") as stream:
            for index in range(40):
                stream.write(f"{index % 11} {(index * 7 + 3) % 23} {1000 + index}\n")
        self.spec = TemporalSourceSpec(
            "fixture", "FX", "events.txt.gz", "gzip", None, "unused", 23, 40, 20
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_extract_is_deterministic_and_compact(self) -> None:
        first = extract_temporal_compact_slice(
            self.path, self.spec, base_edges=12, insert_pool_edges=8
        )
        second = extract_temporal_compact_slice(
            self.path, self.spec, base_edges=12, insert_pool_edges=8
        )
        self.assertEqual(first, second)
        graph, mapping, pool, provenance = first
        self.assertEqual(len(graph.records), 12)
        self.assertEqual(len(pool), 8)
        self.assertEqual(graph.vertices, len(mapping))
        self.assertFalse(provenance["timestamp_order_reconstructed"])

    def test_updates_apply_and_count_physical_records(self) -> None:
        graph, _mapping, pool, _provenance = extract_temporal_compact_slice(
            self.path, self.spec, base_edges=12, insert_pool_edges=8
        )
        for scenario, expected_physical, expected_edges in (
            ("insert", 8, 20),
            ("delete", 8, 4),
            ("mixed", 8, 12),
            ("weight_change", 16, 12),
        ):
            update, physical = build_temporal_update(
                graph, pool, scenario=scenario, batch_size=8
            )
            final_graph = apply_explicit_weighted_updates(graph, update)
            self.assertEqual(physical, expected_physical)
            self.assertEqual(len(update.records), expected_physical)
            self.assertEqual(len(final_graph.records), expected_edges)
            self.assertEqual(
                list(update.records),
                sorted(
                    update.records,
                    key=lambda edge: (
                        edge.src,
                        edge.dst,
                        0 if edge.diff < 0 else 1,
                        edge.weight,
                    ),
                ),
            )
            if scenario == "weight_change":
                for index in range(0, len(update.records), 2):
                    deletion, insertion = update.records[index : index + 2]
                    self.assertEqual((deletion.src, deletion.dst), (insertion.src, insertion.dst))
                    self.assertEqual((deletion.diff, insertion.diff), (-1, 1))


if __name__ == "__main__":
    unittest.main()
