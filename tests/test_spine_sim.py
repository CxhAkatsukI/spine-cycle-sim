from __future__ import annotations

import unittest

from spine_cycle_sim.models import SpineConfig, SpineV0Simulator, classify_hot_cold
from spine_cycle_sim.workloads import Edge
from spine_cycle_sim.workloads import generate_workload, list_workloads


class SpineSimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SpineConfig(max_cycles=2_000_000)

    def small_capacity_config(self) -> SpineConfig:
        return SpineConfig(
            max_vertices=128,
            vs_partition_size=32,
            num_partitions=4,
            hot_shards=2,
            hot_cold_enabled=False,
            batch_size_edges=16,
            num_levels=4,
            max_cycles=200_000,
        )

    def run_case(
        self,
        workload: str,
        vertices: int,
        edges: int,
        config: SpineConfig | None = None,
    ) -> dict:
        if config is None:
            config = self.config
        wl = generate_workload(
            workload,
            vertices=vertices,
            edges=edges,
            source=0,
            num_partitions=config.num_partitions,
            vs_partition_size=config.vs_partition_size,
        )
        return SpineV0Simulator(wl, config).run()

    def test_current_spine_capacity_constants(self) -> None:
        self.assertEqual(self.config.num_levels, 11)
        self.assertEqual(self.config.level_size_ratio, 2)
        self.assertEqual(self.config.level_total_capacity(10), 134_217_728)
        self.assertEqual(self.config.level_family_capacity(1), 16_384)
        self.assertEqual(self.config.level_family_capacity(10), 8_388_608)
        self.assertEqual(self.config.family_total_capacity, 16_891_904)

    def test_workload_list_contains_required_shapes(self) -> None:
        names = set(list_workloads())
        for required in {"chain", "star", "spread", "hotdst", "balanced_partition", "random_rmat"}:
            self.assertIn(required, names)

    def test_chain_passes_and_reports_required_fields(self) -> None:
        result = self.run_case("chain", 64, 63)
        self.assertEqual(result["capacity_status"], "PASS")
        for field in [
            "cycles",
            "simulated_time_ms",
            "edges_per_second",
            "partition_load",
            "level0_occupancy",
            "level1_occupancy",
            "carry_count",
            "hbm_request_count",
            "fifo_stall_cycles",
            "memory_stall_cycles",
            "compute_stall_cycles",
            "maintenance_event_count",
            "maintenance_estimated_cycles",
            "maintenance_scan_passes",
            "maintenance_events",
        ]:
            self.assertIn(field, result)

    def test_balanced_full_plus_one_fits_l1_partition_capacity(self) -> None:
        config = self.small_capacity_config()
        result = self.run_case("balanced_partition", config.max_vertices, 20, config)
        self.assertEqual(result["capacity_status"], "PASS")
        self.assertEqual(result["carry_count"], 1)
        self.assertEqual(result["maintenance_max_target_level"], 1)
        self.assertEqual(result["maintenance_events"][0]["path"], "store_l0")
        self.assertEqual(result["maintenance_events"][1]["path"], "cascade")
        self.assertLessEqual(max(result["level1_occupancy"]), config.level_family_capacity(1))

    def test_one_partition_full_plus_one_skips_to_capacity_safe_level(self) -> None:
        config = self.small_capacity_config()
        result = self.run_case("hotdst", config.max_vertices, 20, config)
        self.assertEqual(result["capacity_status"], "PASS")
        self.assertEqual(result["maintenance_max_target_level"], 3)
        self.assertEqual(result["target_selector_capacity_skips"], 2)

    def test_hot_cold_classifier_promotes_skewed_destinations(self) -> None:
        config = SpineConfig(
            max_vertices=128,
            vs_partition_size=64,
            num_partitions=2,
            hot_shards=2,
            batch_size_edges=8,
            num_levels=4,
            max_cycles=100000,
        )
        edges: list[Edge] = []
        for dst in [0, 1, 2, 3]:
            for i in range(20):
                edges.append(Edge(src=i, dst=dst, weight=1))
        classification = classify_hot_cold(edges, config)
        self.assertFalse(classification.empty_hot_set)
        self.assertGreater(classification.hot_edges, 0)
        self.assertLessEqual(max(classification.cold_partition_edges), config.family_total_capacity)
        self.assertLessEqual(max(classification.hot_shard_edges), config.family_total_capacity)


if __name__ == "__main__":
    unittest.main()
