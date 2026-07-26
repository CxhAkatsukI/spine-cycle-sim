from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.candidate10_workloads import (
    MAX_VERTICES,
    candidate10_workload_cases,
    dirty_boundary_edges,
    duplicate_heavy_edges,
    fallback_forced_edges,
    generated_edges,
    materialize_candidate10_workloads,
    sparse_source_edges,
    task_capacity_edges,
    tiny_mixed_fallback_edges,
)


class Candidate10WorkloadTests(unittest.TestCase):
    def test_generated_edges_match_frozen_host_formula(self) -> None:
        edges = generated_edges(128)
        self.assertEqual(len(edges), 128)
        self.assertEqual((edges[0].source, edges[0].destination), (0, 131_072))
        self.assertEqual(
            (edges[17].source, edges[17].destination),
            (17, 1_179_665),
        )
        self.assertEqual(len({edge.source for edge in edges}), 128)
        self.assertEqual(len({edge.destination // (1 << 20) for edge in edges}), 16)

    def test_boundary_and_duplicate_shapes(self) -> None:
        self.assertEqual(len(dirty_boundary_edges(4_096)), 4_096)
        self.assertEqual(len({edge.source for edge in dirty_boundary_edges(4_096)}), 4_096)
        duplicates = duplicate_heavy_edges(128)
        self.assertEqual(len(duplicates), 128)
        self.assertEqual(len({edge.source for edge in duplicates}), 32)
        self.assertTrue(any(edge.diff < 0 for edge in duplicates))

    def test_sparse_fallback_and_capacity_shapes(self) -> None:
        sparse = sparse_source_edges(16)
        self.assertEqual(sparse[0].source, 0)
        self.assertEqual(sparse[-1].source, MAX_VERTICES - 1)
        self.assertEqual(len(fallback_forced_edges()), 4_112)
        mixed = tiny_mixed_fallback_edges()
        self.assertEqual(len(mixed), 8_193)
        self.assertEqual(len({edge.source for edge in mixed}), 1)
        self.assertEqual(len({edge.destination // (1 << 16) for edge in mixed}), 2)
        self.assertEqual(len(task_capacity_edges()), 65_536)
        self.assertEqual(len(task_capacity_edges(True)), 65_537)

    def test_roles_are_disjoint_and_bind_existing_evidence_names(self) -> None:
        cases = candidate10_workload_cases()
        self.assertEqual(len({case.case_id for case in cases}), len(cases))
        self.assertEqual(len({case.evidence_case for case in cases}), len(cases))
        self.assertEqual(
            {case.role for case in cases}, {"calibration", "holdout", "stress"}
        )
        duplicate = next(case for case in cases if case.case_id == "cal_duplicate_128")
        self.assertEqual(duplicate.role, "calibration")
        self.assertGreater(len(duplicate.edges()), len({edge.source for edge in duplicate.edges()}))

    def test_materialization_is_deterministic_and_keeps_empty_case(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            left = materialize_candidate10_workloads(Path(first))
            right = materialize_candidate10_workloads(Path(second))
            left_rows = {
                row["case_id"]: (row["edges"], row["slice_sha256"])
                for row in left["cases"]
            }
            right_rows = {
                row["case_id"]: (row["edges"], row["slice_sha256"])
                for row in right["cases"]
            }
            self.assertEqual(left_rows, right_rows)
            self.assertEqual(left_rows["cal_zero"][0], 0)
            manifest = json.loads((Path(first) / "manifest.json").read_text())
            self.assertEqual(
                manifest["claim"],
                "frozen_candidate10_host_equivalent_workloads",
            )


if __name__ == "__main__":
    unittest.main()
