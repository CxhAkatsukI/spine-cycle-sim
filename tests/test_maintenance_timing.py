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

    def test_concentrated_batch_skips_undersized_empty_levels(self) -> None:
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

        self.assertEqual(result["capacity_status"], "PASS")
        self.assertEqual(result["maintenance_events"][1]["target_level"], 3)
        self.assertEqual(result["target_selector_capacity_skips"], 2)

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

    def test_l1_cascade_coalesces_output_pages_across_old_and_new_batch(self) -> None:
        config = SpineConfig(
            max_vertices=512,
            vs_partition_size=512,
            num_partitions=1,
            hot_shards=1,
            hot_cold_enabled=False,
            batch_size_edges=4,
            num_levels=3,
            csr_vertices_per_page=256,
            max_cycles=100_000,
        )
        edges = [Edge(i, i + 10, 1) for i in range(4)]
        edges.extend(Edge(i + 4, i + 20, 1) for i in range(4))
        workload = Workload("overlap_pages", config.max_vertices, edges, source=0)
        result = run_workload(workload, config)
        cascade = result["maintenance_events"][1]

        self.assertEqual(result["capacity_status"], "PASS")
        self.assertEqual(cascade["path"], "cascade")
        self.assertEqual(cascade["target_level"], 1)
        self.assertEqual(cascade["pages_visited"], 1)
        self.assertEqual(cascade["page_ids_written"], 1)

    def test_l1_cascade_keeps_disjoint_output_pages(self) -> None:
        config = SpineConfig(
            max_vertices=512,
            vs_partition_size=512,
            num_partitions=1,
            hot_shards=1,
            hot_cold_enabled=False,
            batch_size_edges=4,
            num_levels=3,
            csr_vertices_per_page=256,
            max_cycles=100_000,
        )
        edges = [Edge(i, i + 10, 1) for i in range(4)]
        edges.extend(Edge(256 + i, i + 20, 1) for i in range(4))
        workload = Workload("disjoint_pages", config.max_vertices, edges, source=0)
        result = run_workload(workload, config)
        cascade = result["maintenance_events"][1]

        self.assertEqual(result["capacity_status"], "PASS")
        self.assertEqual(cascade["path"], "cascade")
        self.assertEqual(cascade["target_level"], 1)
        self.assertEqual(cascade["pages_visited"], 1)
        self.assertEqual(cascade["page_ids_written"], 2)

    def test_hw_l1_measure_carry_1024_structural_page_counters(self) -> None:
        config = SpineConfig(
            max_vertices=16 * 1_048_576,
            vs_partition_size=1_048_576,
            num_partitions=16,
            hot_shards=16,
            hot_cold_enabled=False,
            batch_size_edges=1024,
            num_levels=4,
            csr_vertices_per_page=256,
            max_cycles=1_000_000,
        )
        edges: list[Edge] = []
        for src in (0, 1):
            for i in range(1024):
                partition = i % config.num_partitions
                local = i // config.num_partitions
                dst = partition * config.vs_partition_size + local
                edges.append(Edge(src, dst, 1))
        workload = Workload(
            "hw_measure_carry_l1_1024_shape",
            config.max_vertices,
            edges,
            source=0,
        )
        result = run_workload(workload, config)
        cascade = result["maintenance_events"][1]

        self.assertEqual(result["capacity_status"], "PASS")
        self.assertEqual(cascade["path"], "cascade")
        self.assertEqual(cascade["target_level"], 1)
        self.assertEqual(cascade["pages_visited"], 16)
        self.assertEqual(cascade["bits_inspected"], 4096)
        self.assertEqual(cascade["rows_entered"], 16)
        self.assertEqual(cascade["payload_reads"], 1024)
        self.assertEqual(cascade["refill_stalls"], 4176)
        self.assertEqual(cascade["merge_inputs"], 2048)
        self.assertEqual(cascade["outputs"], 2048)
        self.assertEqual(cascade["page_ids_written"], 16)
        self.assertEqual(cascade["structural_estimated_cycles"], 27280)
        self.assertEqual(cascade["scheduled_cycles"], 27280)
        self.assertEqual(cascade["estimated_cycles"], 2_776_656)
        self.assertGreater(result["cycles"], result["execution_cycles"])
        self.assertEqual(
            result["maintenance_estimated_cycles"],
            result["maintenance_calibrated_estimated_cycles"],
        )
        self.assertGreater(result["maintenance_structural_estimated_cycles"], 0)

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
