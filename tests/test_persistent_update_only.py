from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.persistent_update_only import (
    HostRuntimeModel,
    analyze_persistent_update_pair,
)


def update_result(
    *,
    cycles: int = 1000,
    core_mhz: float = 100.0,
    updates: int = 100,
    batches: int = 10,
) -> dict[str, object]:
    return {
        "success": True,
        "measurement_window": "pure_update_only",
        "graph_compute_executed": False,
        "resident_state_persistent": True,
        "correctness_mismatches": 0,
        "device_cycles": cycles,
        "core_mhz": core_mhz,
        "logical_updates": updates,
        "batch_count": batches,
        "backend_traffic": {
            "combined": {
                "requests": 7,
                "bytes": 448,
            },
        },
    }


def host_result(*, updates: int = 100, batches: int = 10) -> dict[str, object]:
    return {
        "updates": updates,
        "batch_count": batches,
        "spine_host_preprocess_ns": 2_000_000,
        "grasu_host_preprocess_ns": 20_000_000,
        "spine_initial_h2d_bytes": 1024,
        "spine_update_h2d_bytes": 256,
        "grasu_initial_h2d_bytes": 4096,
        "grasu_update_h2d_bytes": 256,
    }


class PersistentUpdateOnlyTests(unittest.TestCase):
    def test_host_inclusive_speedup_uses_modeled_architecture_host_cost(self) -> None:
        comparison = analyze_persistent_update_pair(
            dataset_id="toy",
            scenario="insert",
            host=host_result(),
            spine_result=update_result(cycles=1000),
            grasu_result=update_result(cycles=2000),
            runtime=HostRuntimeModel(
                h2d_gbytes_per_second=1.0,
                launch_sync_microseconds_per_batch=10.0,
            ),
        )
        rows = {row["system"]: row for row in comparison["rows"]}
        self.assertAlmostEqual(rows["spine"]["device_seconds"], 0.00001)
        self.assertAlmostEqual(rows["grasu_regraph"]["device_seconds"], 0.00002)
        self.assertGreater(comparison["spine_speedup"]["modeled_host_inclusive"], 1.0)
        self.assertLess(comparison["spine_speedup"]["device_only"], 3.0)

    def test_rejects_non_update_only_measurement_window(self) -> None:
        spine = update_result()
        spine["measurement_window"] = "dynamic_e2e_to_convergence"
        with self.assertRaisesRegex(ValueError, "not pure update-only"):
            analyze_persistent_update_pair(
                dataset_id="toy",
                scenario="insert",
                host=host_result(),
                spine_result=spine,
                grasu_result=update_result(),
                runtime=HostRuntimeModel(12.0, 10.0),
            )

    def test_rejects_graph_compute_execution(self) -> None:
        grasu = update_result()
        grasu["graph_compute_executed"] = True
        with self.assertRaisesRegex(ValueError, "executed graph compute"):
            analyze_persistent_update_pair(
                dataset_id="toy",
                scenario="insert",
                host=host_result(),
                spine_result=update_result(),
                grasu_result=grasu,
                runtime=HostRuntimeModel(12.0, 10.0),
            )

    def test_rejects_shape_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "different trace shapes"):
            analyze_persistent_update_pair(
                dataset_id="toy",
                scenario="insert",
                host=host_result(),
                spine_result=update_result(updates=100),
                grasu_result=update_result(updates=101),
                runtime=HostRuntimeModel(12.0, 10.0),
            )

    def test_rejects_host_shape_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "host benchmark"):
            analyze_persistent_update_pair(
                dataset_id="toy",
                scenario="insert",
                host=host_result(updates=99),
                spine_result=update_result(updates=100),
                grasu_result=update_result(updates=100),
                runtime=HostRuntimeModel(12.0, 10.0),
            )

    def test_validates_runtime_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "H2D bandwidth"):
            HostRuntimeModel(0.0, 10.0)
        with self.assertRaisesRegex(ValueError, "launch/sync"):
            HostRuntimeModel(12.0, -1.0)


if __name__ == "__main__":
    unittest.main()
