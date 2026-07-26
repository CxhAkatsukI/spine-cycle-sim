from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from spine_cycle_sim.experiments.large_real_pagerank import (
    build_large_real_update,
    classify_hot_destinations,
    evaluate_large_real_runtime_gate,
    extract_large_real_slice,
    spine_hot_hash,
    validate_large_real_pagerank_manifest,
)
from spine_cycle_sim.experiments.shared_workloads import SliceGraph, SliceRecord


class LargeRealPageRankTests(unittest.TestCase):
    def test_runtime_gate_preserves_complete_over_limit_observations(self) -> None:
        manifest = {
            "runtime_contract": {"host_runtime_limit_seconds_per_system": 30},
            "runs": [{"run_id": "large"}],
        }
        gate = evaluate_large_real_runtime_gate(
            manifest,
            [
                {"run_id": "large", "system": "spine", "host_wall_seconds": 31.0},
                {
                    "run_id": "large",
                    "system": "grasu_regraph",
                    "host_wall_seconds": 20.0,
                },
            ],
        )
        self.assertEqual(gate["status"], "FAIL")
        self.assertFalse(gate["pass"])
        self.assertEqual(gate["failed_systems"], [{"run_id": "large", "system": "spine"}])

    def test_runtime_gate_rejects_incomplete_rows(self) -> None:
        manifest = {
            "runtime_contract": {"host_runtime_limit_seconds_per_system": 30},
            "runs": [{"run_id": "large"}],
        }
        with self.assertRaisesRegex(ValueError, "incomplete"):
            evaluate_large_real_runtime_gate(
                manifest,
                [
                    {
                        "run_id": "large",
                        "system": "spine",
                        "host_wall_seconds": 20.0,
                    }
                ],
            )

    def test_frozen_manifest_requires_candidate10_hls_v3(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (
            root
            / "configs/experiments/hls_full_pagerank_real_large_runtime_20260726.json"
        )
        manifest = validate_large_real_pagerank_manifest(root, source)
        self.assertEqual(manifest["required_profile_set"], "candidate10_hls_v3")
        with tempfile.TemporaryDirectory() as temporary:
            invalid = json.loads(source.read_text(encoding="ascii"))
            invalid["required_profile_set"] = "legacy"
            invalid_path = Path(temporary) / "invalid.json"
            invalid_path.write_text(
                json.dumps(invalid, sort_keys=True), encoding="ascii"
            )
            with self.assertRaisesRegex(ValueError, "profile-set identity"):
                validate_large_real_pagerank_manifest(root, invalid_path)

    def test_extraction_is_deterministic_and_uses_real_vertex_domain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "graph.mtx"
            source.write_text(
                "%%MatrixMarket matrix coordinate pattern general\n"
                "8 8 8\n"
                "1 2\n2 3\n3 4\n4 1\n1 3\n2 4\n5 6\n7 8\n",
                encoding="ascii",
            )
            first, mapping = extract_large_real_slice(
                source, case_id="small", vertices=8, edge_limit=6
            )
            second, second_mapping = extract_large_real_slice(
                source, case_id="small", vertices=8, edge_limit=6
            )
            self.assertEqual(first, second)
            self.assertEqual(mapping, second_mapping)
            self.assertEqual(first.vertices, 4)
            self.assertEqual(len(first.records), 6)
            self.assertEqual(len(mapping), 4)

    def test_update_is_disjoint_and_spread(self) -> None:
        graph = SliceGraph(
            "g",
            32,
            tuple(SliceRecord(vertex, (vertex + 1) % 32) for vertex in range(32)),
        )
        update = build_large_real_update(graph, mapped_vertices=32, batch_size=8)
        existing = {(edge.src, edge.dst) for edge in graph.records}
        self.assertEqual(len(update.records), 8)
        self.assertEqual(len({edge.src for edge in update.records}), 8)
        self.assertFalse(any((edge.src, edge.dst) in existing for edge in update.records))

    def test_hot_classifier_matches_indegree_order_and_hash(self) -> None:
        graph = SliceGraph(
            "hot",
            32,
            tuple(
                [SliceRecord(source, 7) for source in range(10)]
                + [SliceRecord(source + 10, 8) for source in range(5)]
                + [SliceRecord(20, destination) for destination in range(10, 20)]
            ),
        )
        update = SliceGraph("u", 32, (SliceRecord(30, 9),))
        classification = classify_hot_destinations(
            graph, update, family_capacity=12
        )
        self.assertEqual(classification["hot_vertices"][0], 7)
        self.assertLessEqual(max(classification["cold_family_edges"]), 12)
        self.assertLessEqual(max(classification["hot_shard_edges"]), 12)
        self.assertEqual(spine_hot_hash(7), spine_hot_hash(7))

    def test_classifier_rejects_superhub(self) -> None:
        graph = SliceGraph(
            "hub",
            32,
            tuple(SliceRecord(source, 31) for source in range(16)),
        )
        with self.assertRaisesRegex(ValueError, "exceeds family cap"):
            classify_hot_destinations(
                graph, SliceGraph("u", 32, ()), family_capacity=8
            )


if __name__ == "__main__":
    unittest.main()
