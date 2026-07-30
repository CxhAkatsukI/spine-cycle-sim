from __future__ import annotations

import unittest

from spine_cycle_sim.evidence.workload_energy import (
    WorkloadEnergyError,
    analyze_workload_energy,
)


def system_row(execution: str, system: str) -> dict[str, object]:
    return {
        "execution_id": execution,
        "group_id": "pair",
        "dataset_id": "trace",
        "algorithm": "connected_components",
        "system": system,
        "cycles": 1_000,
        "clock_mhz": 100,
        "dram_energy_pj": 2_000_000,
    }


def activity(execution: str, system: str) -> list[dict[str, object]]:
    names = {
        "spine": (("hbm_frontend", 900), ("maintenance", 100), ("compute", 800)),
        "grasu_regraph_k4_shared": (
            ("hbm_frontend", 950),
            ("update_pma", 50),
            ("compute_pipeline_aggregate", 900),
        ),
    }
    return [
        {
            "execution_id": execution,
            "system": system,
            "component": component,
            "component_cycles": cycles,
        }
        for component, cycles in names[system]
    ]


def power(system: str) -> dict[str, object]:
    return {
        "build_id": f"{system}-sssp",
        "system": system,
        "algorithm": "weighted_sssp",
        "dynamic_w": 10,
        "device_static_w": 1,
        "ulp_power_w": 5,
        "platform_dynamic_residual_w": 5,
        "hbm_subsystem": 1,
        "update_maintenance": 1,
        "graph_compute": 1,
        "stream_fifos": 1,
        "other_user_logic": 1,
    }


class WorkloadEnergyTests(unittest.TestCase):
    def test_component_and_total_ledgers_close(self) -> None:
        systems = [
            system_row("spine", "spine"),
            system_row("grasu", "grasu_regraph_k4_shared"),
        ]
        activities = activity("spine", "spine") + activity(
            "grasu", "grasu_regraph_k4_shared"
        )
        ledger = analyze_workload_energy(
            systems,
            activities,
            [power("spine"), power("grasu_regraph")],
        )
        self.assertEqual(ledger["status"], "PASS")
        self.assertEqual(len(ledger["pair_rows"]), 1)
        self.assertEqual(len(ledger["component_rows"]), 10)
        self.assertTrue(all(row["energy_ledger_closed"] for row in ledger["system_rows"]))
        self.assertTrue(
            all(
                row["power_profile_role"] == "algorithm_proxy_weighted_sssp"
                for row in ledger["system_rows"]
            )
        )

    def test_rejects_component_activity_beyond_e2e_window(self) -> None:
        systems = [
            system_row("spine", "spine"),
            system_row("grasu", "grasu_regraph_k4_shared"),
        ]
        activities = activity("spine", "spine") + activity(
            "grasu", "grasu_regraph_k4_shared"
        )
        activities[0]["component_cycles"] = 1_001
        with self.assertRaisesRegex(WorkloadEnergyError, "exceeds"):
            analyze_workload_energy(
                systems,
                activities,
                [power("spine"), power("grasu_regraph")],
            )


if __name__ == "__main__":
    unittest.main()
