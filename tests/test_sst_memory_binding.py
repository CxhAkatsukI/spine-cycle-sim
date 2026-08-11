from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.sst_binding import (
    SstMemoryBinding,
    _spine_automatic_hot_vertices,
    _spine_hot_hash,
    grasu_normalized_memory_binding,
    make_sst_memory_binding,
    spine_memory_binding,
)
from scripts.analyze_sparse_hbm_equivalence import compare_case


ROOT = Path(__file__).resolve().parents[1]


class SstMemoryBindingTests(unittest.TestCase):
    def test_auto_hot_skips_vertices_from_already_fit_partitions(self) -> None:
        indegree = {destination: 10 for destination in range(8)}
        indegree[64] = 15
        promoted = _spine_automatic_hot_vertices(
            indegree,
            [80, 15, 0, 0],
            {
                "partitions": 4,
                "levels": 5,
                "level_ratio": 2,
                "max_sort_edges": 8,
                "vertex_partition_size": 64,
            },
        )
        self.assertNotIn(64, promoted)
        self.assertTrue(set(promoted) <= set(range(8)))

    def test_auto_hot_matches_hls_hash_collision_rejection(self) -> None:
        same_shard: list[int] = []
        other_shard: list[int] = []
        for destination in range(256):
            target = same_shard if _spine_hot_hash(destination) % 4 == 0 else other_shard
            target.append(destination)
            if len(same_shard) >= 3 and len(other_shard) >= 3:
                break
        ordered = same_shard[:3] + other_shard[:3]
        indegree = {
            destination: degree
            for destination, degree in zip(
                ordered, (30, 29, 28, 27, 26, 25), strict=True
            )
        }
        with self.assertRaisesRegex(ValueError, "overflows hot shard"):
            _spine_automatic_hot_vertices(
                indegree,
                [sum(indegree.values()), 0, 0, 0],
                {
                    "partitions": 4,
                    "levels": 5,
                    "level_ratio": 2,
                    "max_sort_edges": 8,
                    "vertex_partition_size": 256,
                },
            )

    def test_grasu_normalized_reachable_channels(self) -> None:
        profile = json.loads(
            (
                ROOT
                / "configs"
                / "architectures"
                / "grasu_regraph_normalized_pagerank_spine23.json"
            ).read_text(encoding="utf-8")
        )
        binding = grasu_normalized_memory_binding(profile)
        self.assertEqual(binding.physical_channels, 32)
        self.assertEqual(binding.reachable_channels, (0, 1, 2, 3, 30))
        self.assertEqual(binding.instantiated_channels, (0, 1, 2, 3, 30))
        self.assertTrue(binding.sparse)
        self.assertIn("excludes_unbound", binding.energy_claim)

    def test_grasu_full_binding_preserves_reachable_set(self) -> None:
        profile = json.loads(
            (
                ROOT
                / "configs"
                / "architectures"
                / "grasu_regraph_normalized_weighted_spine23.json"
            ).read_text(encoding="utf-8")
        )
        binding = grasu_normalized_memory_binding(profile, instantiate_all=True)
        self.assertEqual(binding.reachable_channels, (0, 1, 2, 3, 30))
        self.assertEqual(binding.instantiated_channels, tuple(range(32)))
        self.assertFalse(binding.sparse)

    def test_grasu_interleaved_binding_instantiates_frozen_23_channels(self) -> None:
        profile = json.loads(
            (
                ROOT
                / "configs"
                / "architectures"
                / "grasu_regraph_candidate10_k1_multipart_pagerank_fullgraph_v7.json"
            ).read_text(encoding="utf-8")
        )
        binding = grasu_normalized_memory_binding(profile)
        self.assertEqual(binding.physical_channels, 32)
        self.assertEqual(binding.reachable_channels, tuple(range(23)))
        self.assertEqual(binding.instantiated_channels, tuple(range(23)))

    def test_spine_single_partition_reachable_channels(self) -> None:
        profile = json.loads(
            (
                ROOT / "configs" / "architectures" / "spine_latest_afb8199.json"
            ).read_text(encoding="utf-8")
        )
        binding = spine_memory_binding(
            profile,
            [ROOT / "tests" / "data" / "shared_comparison" / "syn_chain_v64.slice"],
        )
        self.assertEqual(
            binding.reachable_channels,
            (0, 16, 17, 18, 19, 20, 21, 22),
        )

    def test_spine_uses_cold_partition_and_hot_shard_channel_numbers(self) -> None:
        profile = json.loads(
            (
                ROOT / "configs" / "architectures" / "spine_latest_afb8199.json"
            ).read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            workload = Path(tmp) / "binding.slice"
            workload.write_text(
                "# vertices=2097154\n"
                "0 1048577 1 1\n"
                "0 17 1 1\n",
                encoding="ascii",
            )
            cold = spine_memory_binding(profile, [workload])
            hot = spine_memory_binding(profile, [workload], hot_vertices=(17,))
        self.assertIn(1, cold.reachable_channels)
        self.assertIn(1, hot.reachable_channels)
        self.assertIn(5, hot.reachable_channels)

    def test_spine_auto_hot_promotion_binds_hashed_graph_channels(self) -> None:
        profile = json.loads(
            (
                ROOT / "configs" / "architectures" / "spine_latest_afb8199.json"
            ).read_text(encoding="utf-8")
        )
        profile["parameters"]["max_sort_edges"] = 2
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            workload = Path(tmp) / "auto_hot.slice"
            rows = ["# vertices=512"]
            # Three promotions are required; dst=2 hashes to graph channel 1.
            for destination in range(11):
                rows.extend(
                    f"{source} {destination} 1 1" for source in range(30)
                )
            workload.write_text("\n".join(rows) + "\n", encoding="ascii")
            binding = spine_memory_binding(profile, [workload])
        self.assertIn(0, binding.reachable_channels)
        self.assertTrue(
            any(channel in binding.reachable_channels for channel in range(1, 16))
        )
        self.assertTrue(set(range(16, 23)) <= set(binding.reachable_channels))

    def test_binding_rejects_omitted_reachable_channel(self) -> None:
        with self.assertRaisesRegex(ValueError, "omit a reachable"):
            SstMemoryBinding(32, (0, 30), (0,))

    def test_binding_rejects_unsorted_or_out_of_range_channels(self) -> None:
        with self.assertRaisesRegex(ValueError, "sorted and unique"):
            SstMemoryBinding(32, (2, 1), (1, 2))
        with self.assertRaisesRegex(ValueError, "out-of-range"):
            make_sst_memory_binding(32, (32,), instantiate_all=False)

    def test_equivalence_analyzer_checks_results_and_active_dram_files(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            full = root / "full"
            sparse = root / "sparse"
            result = {
                "cycles": 123,
                "backend_requests": 7,
                "correctness_mismatches": 0,
            }
            for run, channels, wall in (
                (full, tuple(range(32)), 4.0),
                (sparse, (0, 30), 1.0),
            ):
                run.mkdir()
                (run / "result.json").write_text(
                    json.dumps(result, sort_keys=True) + "\n", encoding="utf-8"
                )
                binding = SstMemoryBinding(32, (0, 30), channels).as_manifest()
                (run / "manifest.json").write_text(
                    json.dumps(
                        {
                            "sst_memory_binding": binding,
                            "sst_host_wall_seconds": wall,
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                for channel in channels:
                    channel_dir = run / "dram" / f"channel{channel}"
                    channel_dir.mkdir(parents=True)
                    for filename in ("dramsim3.json", "dramsim3.txt"):
                        (channel_dir / filename).write_text(
                            f"channel={channel}\n", encoding="utf-8"
                        )
            evidence = compare_case("unit", full, sparse)
        self.assertEqual(evidence["cycles"], 123)
        self.assertEqual(evidence["host_runtime_speedup"], 4.0)
        self.assertEqual(evidence["status"], "PASS_EXACT_EQUIVALENCE")


if __name__ == "__main__":
    unittest.main()
