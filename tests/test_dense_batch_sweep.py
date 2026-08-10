from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.dense_batch_sweep import (
    DENSE_SWEEP_BATCH_SIZES,
    DENSE_SWEEP_PATTERNS,
    build_dense_base_graph,
    build_dense_batch_manifest,
    build_dense_update,
    validate_spine_dense_capacity_failure,
    validate_dense_batch_manifest,
    validate_grasu_dense_capacity_rejection,
)


class DenseBatchSweepTests(unittest.TestCase):
    def test_patterns_have_expected_source_pressure(self) -> None:
        graph = build_dense_base_graph()
        concentrated = build_dense_update(graph, "source_concentrated", 16384)
        scattered = build_dense_update(graph, "source_scattered", 16384)
        concentrated_sources = {edge.src for edge in concentrated.records}
        scattered_sources = {edge.src for edge in scattered.records}
        self.assertLessEqual(len(concentrated_sources), 3)
        self.assertEqual(len(scattered_sources), graph.vertices)
        self.assertEqual(len(concentrated.records), 16384)
        self.assertEqual(len(scattered.records), 16384)

    def test_manifest_round_trip_and_axis_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest = build_dense_batch_manifest(
                root,
                output_dir=root / "workloads",
                manifest_path=manifest_path,
            )
            validated = validate_dense_batch_manifest(root, manifest_path)
            self.assertEqual(validated, manifest)
            self.assertEqual(
                len(validated["runs"]),
                len(DENSE_SWEEP_PATTERNS) * len(DENSE_SWEEP_BATCH_SIZES),
            )

    def test_validator_rejects_modified_axis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            build_dense_batch_manifest(
                root,
                output_dir=root / "workloads",
                manifest_path=manifest_path,
            )
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["batch_contract"]["batch_sizes"][-1] = 32768
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "size axis"):
                validate_dense_batch_manifest(root, manifest_path)

    def test_spine_capacity_boundary_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest = build_dense_batch_manifest(
                root,
                output_dir=root / "workloads",
                manifest_path=manifest_path,
            )
            statuses = {
                (run["pattern"], run["batch_size"]): run[
                    "expected_spine_capacity_status"
                ]
                for run in manifest["runs"]
            }
            for pattern in DENSE_SWEEP_PATTERNS:
                self.assertEqual(statuses[(pattern, 8192)], "PASS")
                self.assertEqual(statuses[(pattern, 16384)], "PASS")
            grasu_statuses = {
                (run["pattern"], run["batch_size"]): run[
                    "expected_grasu_capacity_status"
                ]
                for run in manifest["runs"]
            }
            for pattern in DENSE_SWEEP_PATTERNS:
                self.assertEqual(grasu_statuses[(pattern, 4096)], "PASS")
                self.assertEqual(grasu_statuses[(pattern, 8192)], "FAIL")

    def test_capacity_failure_validator_is_fail_closed(self) -> None:
        run = {
            "expected_spine_capacity_status": "FAIL",
            "graph": {"vertices": 8192, "records": 8192},
            "physical_records": 16384,
            "final_edges": 24576,
        }
        result = {
            "success": False,
            "mode": "spine_pagerank",
            "dynamic_update": True,
            "failure": (
                "maintenance: Spine cold level hierarchy has no capacity-safe free target"
            ),
            "vertices": 8192,
            "initial_edges": 8192,
            "update_edges": 16384,
            "materialized_snapshot_edges": 24576,
            "maintenance_target_level": -1,
            "maintenance_logical_overflow_events": 1,
            "maintenance_cycles": 100,
            "maintenance_persisted_edges": 0,
            "compute_backend_requests": 0,
            "pagerank_completed_iterations": 0,
        }
        self.assertEqual(validate_spine_dense_capacity_failure(run, result), [])
        result["failure"] = ""
        self.assertEqual(
            validate_spine_dense_capacity_failure(run, result), ["failure"]
        )

    def test_grasu_capacity_rejection_comes_from_pinned_profile(self) -> None:
        run = {
            "expected_grasu_capacity_status": "FAIL",
            "expected_grasu_capacity_reason": "degree_reorder_entries",
            "physical_records": 8192,
        }
        profile = {"parameters": {"grasu_degree_reorder_entries": 4096}}
        self.assertEqual(validate_grasu_dense_capacity_rejection(run, profile), [])
        profile["parameters"]["grasu_degree_reorder_entries"] = 8192
        self.assertIn(
            "profile_entries", validate_grasu_dense_capacity_rejection(run, profile)
        )


if __name__ == "__main__":
    unittest.main()
