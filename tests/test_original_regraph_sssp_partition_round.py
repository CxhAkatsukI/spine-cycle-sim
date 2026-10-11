"""Reject silent input transformation and incomplete partition diagnostics."""

import copy
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.preparation import select
from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.analysis import MATRIX, coverage, matrix
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.preparation import write_words


class PartitionRoundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def source(self, text):
        path = self.root / "source.txt"
        path.write_text(text, encoding="ascii")
        return path

    def test_induced_selection_keeps_direction_holes_and_deduplicates(self):
        source = self.source("1 3\n3 1\n1 3\n4 1\n0 1\n")
        graph, report = select(source, self.root / "out.txt", vertices=3, expected_sha256=sha256_file(source))
        self.assertEqual(graph.vertices, 3)
        self.assertEqual([(e.src, e.dst) for e in graph.records], [(0, 2), (2, 0)])
        self.assertEqual(report["duplicate_rows_removed"], 1)
        self.assertEqual(report["excluded_rows"], 2)
        self.assertEqual(report["source_rows"], 5)
        self.assertTrue(all(1 <= e.weight <= 31 for e in graph.records))

    def test_reject_identity_extent_and_empty_root(self):
        source = self.source("2 3\n3 2\n")
        with self.assertRaises(ValueError):
            select(source, self.root / "out.txt", vertices=3, expected_sha256="0" * 64)
        with self.assertRaises(ValueError):
            select(source, self.root / "out.txt", vertices=3, expected_sha256=sha256_file(source))
        with self.assertRaises(ValueError):
            select(source, self.root / "out.txt", vertices=4, expected_sha256=sha256_file(source))

    def test_reject_negative_and_extra_columns(self):
        for text in ("-1 2\n", "1 2 3\n"):
            source = self.source(text)
            with self.assertRaises(ValueError):
                select(source, self.root / "out.txt", vertices=2, expected_sha256=sha256_file(source))

    def test_extent_matches_author_maximum_ID_not_unused_trailing_ID(self):
        source = self.source("1 3\n3 1\n")
        graph, report = select(source, self.root / "out.txt", vertices=4, expected_sha256=sha256_file(source))
        self.assertEqual(graph.vertices, 3)
        self.assertEqual(report["requested_external_id_upper_bound"], 4)
        self.assertEqual(report["trailing_unused_IDs_omitted_by_author_loader"], 1)

    def test_four_live_partitions_required(self):
        write_words(self.root / "csr_destinations.u32le", [0, 65536, 131072, 196608])
        layout = {"summary": {"vertices": 258048, "aligned_vertices": 262144,
                              "partitions": 4, "little": 4, "big": 0, "logical_edges": 4},
                  "tasks": [{"kind": "dense"}] * 16}
        result = coverage(layout, self.root)
        self.assertEqual(result["logical_edges_by_destination_partition"], [1, 1, 1, 1])
        self.assertFalse(result["independent_runtime_per_worker_counters_available"])
        layout["summary"]["partitions"] = 3
        with self.assertRaises(ValueError):
            coverage(layout, self.root)

    def cases(self):
        return [{"mode": mode, "latency": latency, "reverse": reverse,
                 "paths": [{"cycles": latency + 1, "read_bytes": 100}],
                 "outputs": [{"sha256": "frozen"}]} for mode, latency, reverse in MATRIX]

    def test_matrix_complete_order_and_resource_claim(self):
        rows = self.cases()
        self.assertFalse(matrix(rows)["strict_resource_matched_performance_admitted"])
        with self.assertRaises(ValueError):
            matrix(rows[:-1])
        rows[1]["paths"][0]["cycles"] += 1
        with self.assertRaises(ValueError):
            matrix(rows)

    def test_latency_cannot_change_output_or_traffic(self):
        for change in ("state", "traffic"):
            rows = copy.deepcopy(self.cases())
            for row in rows[-2:]:
                if change == "state":
                    row["outputs"][0]["sha256"] = "changed"
                else:
                    row["paths"][0]["read_bytes"] += 1
            with self.assertRaises(ValueError):
                matrix(rows)


if __name__ == "__main__":
    unittest.main()
