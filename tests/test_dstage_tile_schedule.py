from __future__ import annotations

import unittest

from spine_cycle_sim.models import SpineConfig, SpineV0Simulator
from spine_cycle_sim.models.dstage import build_tile_schedule
from spine_cycle_sim.workloads import (
    generate_partition_tile_workload,
    generate_tile_workload,
)


class DStageTileScheduleTests(unittest.TestCase):
    def test_boundary_mixed_tile_schedule(self) -> None:
        config = SpineConfig(max_cycles=1_000_000, hot_cold_enabled=False)
        workload = generate_tile_workload(
            [4096, 4097],
            tile_vertices=config.conv_tile_vertices,
            max_vertices=config.max_vertices,
        )

        schedule = build_tile_schedule(workload.edges, workload.vertices, config)

        self.assertEqual(schedule.touched_tiles, 2)
        self.assertEqual(schedule.fast_path_tiles, 1)
        self.assertEqual(schedule.full_path_tiles, 1)
        self.assertEqual(schedule.gathered_vertex_words, 4096)
        self.assertEqual(schedule.scattered_vertex_words, 4096)
        self.assertEqual(schedule.swept_vertex_words, 8196)
        self.assertEqual([entry.path for entry in schedule.entries], ["fast", "full"])
        self.assertEqual([entry.tile_work for entry in schedule.entries], [4096, 4097])

    def test_simulator_exposes_tile_schedule_backend(self) -> None:
        config = SpineConfig(max_cycles=2_000_000, hot_cold_enabled=False)
        workload = generate_tile_workload(
            [128, 8192],
            tile_vertices=config.conv_tile_vertices,
            max_vertices=config.max_vertices,
        )
        result = SpineV0Simulator(workload, config).run()

        self.assertEqual(result["capacity_status"], "PASS")
        self.assertEqual(result["dstage_tile_fast_path_tiles"], 1)
        self.assertEqual(result["dstage_tile_full_path_tiles"], 1)
        self.assertEqual(
            [entry["tile_work"] for entry in result["dstage_tile_schedule"]],
            [128, 8192],
        )

    def test_multi_partition_tile_work_schedule(self) -> None:
        config = SpineConfig(max_cycles=2_000_000, hot_cold_enabled=False)
        workload = generate_partition_tile_workload(
            {0: [4096, 4097], 1: [128, 8192]},
            tile_vertices=config.conv_tile_vertices,
            vs_partition_size=config.vs_partition_size,
            max_vertices=config.max_vertices,
        )

        schedule = build_tile_schedule(workload.edges, workload.vertices, config)

        self.assertEqual(len(schedule.entries), 4)
        self.assertEqual(schedule.fast_path_tiles, 2)
        self.assertEqual(schedule.full_path_tiles, 2)
        self.assertEqual(
            [(entry.partition, entry.tile) for entry in schedule.entries],
            [(0, 0), (0, 1), (1, 0), (1, 1)],
        )
        self.assertEqual(
            [entry.tile_work for entry in schedule.entries],
            [4096, 4097, 128, 8192],
        )


if __name__ == "__main__":
    unittest.main()
