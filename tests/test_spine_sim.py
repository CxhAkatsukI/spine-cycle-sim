from __future__ import annotations

import unittest

from spine_cycle_sim.models import SpineConfig, SpineV0Simulator
from spine_cycle_sim.workloads import generate_workload, list_workloads


class SpineSimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SpineConfig(max_cycles=2_000_000)

    def run_case(self, workload: str, vertices: int, edges: int) -> dict:
        wl = generate_workload(
            workload,
            vertices=vertices,
            edges=edges,
            source=0,
            num_partitions=self.config.num_partitions,
        )
        return SpineV0Simulator(wl, self.config).run()

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
        ]:
            self.assertIn(field, result)

    def test_balanced_full_plus_one_fits_l1_partition_capacity(self) -> None:
        result = self.run_case("balanced_partition", 262144, 131073)
        self.assertEqual(result["capacity_status"], "PASS")
        self.assertEqual(result["carry_count"], 1)
        self.assertLessEqual(max(result["partition_load"]), self.config.level1_capacity_per_partition)

    def test_one_partition_full_plus_one_fails_l1_partition_capacity(self) -> None:
        result = self.run_case("hotdst", 262144, 131073)
        self.assertEqual(result["capacity_status"], "FAIL")
        self.assertEqual(result["capacity_failure"]["reason"], "level_partition_capacity")
        self.assertEqual(result["capacity_failure"]["failure_level"], 1)
        self.assertEqual(result["capacity_failure"]["failure_partition"], 0)
        self.assertGreater(
            result["capacity_failure"]["failure_partition_edges"],
            result["capacity_failure"]["failure_partition_capacity"],
        )


if __name__ == "__main__":
    unittest.main()
