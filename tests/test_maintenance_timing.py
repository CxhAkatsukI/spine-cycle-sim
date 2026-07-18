from __future__ import annotations

import unittest

from spine_cycle_sim.models import SpineConfig, SpineV0Simulator
from spine_cycle_sim.workloads import Edge, Workload, generate_workload


def run_workload(workload: Workload, config: SpineConfig) -> dict:
    return SpineV0Simulator(workload, config).run()


class MaintenanceTimingTests(unittest.TestCase):
    def test_cold_l0_store_counts_hls_scan_passes(self) -> None:
        config = SpineConfig(
            max_vertices=128,
            vs_partition_size=32,
            num_partitions=4,
            hot_shards=2,
            hot_cold_enabled=False,
            batch_size_edges=64,
            num_levels=4,
            max_cycles=100_000,
        )
        workload = generate_workload(
            "hotdst",
            vertices=config.max_vertices,
            edges=8,
            source=0,
            num_partitions=config.num_partitions,
            vs_partition_size=config.vs_partition_size,
        )
        result = run_workload(workload, config)
        event = result["maintenance_events"][0]

        self.assertEqual(result["capacity_status"], "PASS")
        self.assertEqual(event["path"], "store_l0")
        self.assertEqual(event["target_level"], 0)
        self.assertEqual(event["diagnostic_scan_passes"], 1)
        self.assertEqual(event["pre_count_scan_passes"], config.num_partitions)
        self.assertEqual(event["write_scan_passes"], 1)
        self.assertEqual(event["scan_passes"], 6)

    def test_balanced_batch_exposes_l1_cascade_cursor_work(self) -> None:
        config = SpineConfig(
            max_vertices=128,
            vs_partition_size=32,
            num_partitions=4,
            hot_shards=2,
            hot_cold_enabled=False,
            batch_size_edges=16,
            num_levels=4,
            max_cycles=200_000,
        )
        workload = generate_workload(
            "balanced_partition",
            vertices=config.max_vertices,
            edges=20,
            source=0,
            num_partitions=config.num_partitions,
            vs_partition_size=config.vs_partition_size,
        )
        result = run_workload(workload, config)
        cascade = result["maintenance_events"][1]

        self.assertEqual(result["capacity_status"], "PASS")
        self.assertEqual(cascade["path"], "cascade")
        self.assertEqual(cascade["target_level"], 1)
        self.assertEqual(cascade["new_batch_filter_passes"], config.num_partitions)
        self.assertGreater(cascade["payload_reads"], 0)
        self.assertEqual(
            cascade["bits_inspected"],
            cascade["pages_visited"] * config.csr_vertices_per_page,
        )

    def test_concentrated_batch_reports_l1_capacity_overflow(self) -> None:
        config = SpineConfig(
            max_vertices=128,
            vs_partition_size=32,
            num_partitions=4,
            hot_shards=2,
            hot_cold_enabled=False,
            batch_size_edges=16,
            num_levels=4,
            max_cycles=200_000,
        )
        workload = generate_workload(
            "hotdst",
            vertices=config.max_vertices,
            edges=20,
            source=0,
            num_partitions=config.num_partitions,
            vs_partition_size=config.vs_partition_size,
        )
        result = run_workload(workload, config)

        self.assertEqual(result["capacity_status"], "FAIL")
        self.assertEqual(result["capacity_failure"]["reason"], "level_family_capacity")
        self.assertEqual(result["capacity_failure"]["failure_level"], 1)
        self.assertEqual(result["capacity_failure"]["maintenance_path"], "cascade")

    def test_l0_store_uses_coalesced_edge_count_for_output(self) -> None:
        config = SpineConfig(
            max_vertices=16,
            vs_partition_size=16,
            num_partitions=1,
            hot_shards=1,
            hot_cold_enabled=False,
            batch_size_edges=64,
            num_levels=3,
            max_cycles=100_000,
        )
        workload = Workload(
            "duplicate_edge",
            vertices=16,
            edges=[Edge(1, 2, 1) for _ in range(20)],
            source=1,
        )
        result = run_workload(workload, config)
        event = result["maintenance_events"][0]

        self.assertEqual(result["capacity_status"], "PASS")
        self.assertEqual(event["input_edges"], 20)
        self.assertEqual(event["output_edges"], 1)
        self.assertEqual(event["page_ids_written"], 1)

    def test_hot_metadata_keeps_scanning_zero_input_groups(self) -> None:
        config = SpineConfig(
            max_vertices=128,
            vs_partition_size=128,
            num_partitions=1,
            hot_shards=4,
            hot_cold_enabled=True,
            batch_size_edges=8,
            num_levels=3,
            max_cycles=300_000,
        )
        edges = [Edge(i, 0, 1) for i in range(8)]
        edges.extend(Edge(i % 64, (i % 56) + 1, 1) for i in range(56))
        workload = Workload("hot_sparse_batches", 128, edges, source=0)
        result = run_workload(workload, config)
        events = result["maintenance_events"]

        self.assertEqual(result["capacity_status"], "PASS")
        self.assertTrue(result["hot_enabled"])
        self.assertEqual(events[0]["group"], "cold")
        self.assertEqual(events[0]["input_edges"], 0)
        self.assertEqual(events[0]["output_edges"], 0)
        self.assertEqual(events[0]["scan_passes"], 2)
        self.assertEqual(events[1]["group"], "hot")
        self.assertGreater(events[1]["input_edges"], 0)
        self.assertTrue(
            any(
                event["group"] == "hot"
                and event["path"] == "cascade"
                and event["input_edges"] == 0
                and event["output_edges"] > 0
                for event in events
            )
        )


if __name__ == "__main__":
    unittest.main()
