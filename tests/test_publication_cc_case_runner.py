from __future__ import annotations

from types import SimpleNamespace
import unittest

from scripts.run_publication_cc_case import (
    expected_profile_hash,
    final_state_identity,
    result_row,
)


class PublicationConnectedComponentsRunnerTests(unittest.TestCase):
    def test_final_state_identity_requires_and_hashes_all_labels(self) -> None:
        first = final_state_identity({"labels": [0, 0, 2, 2]})
        second = final_state_identity({"labels": [0, 0, 2, 2]})
        self.assertEqual(first, second)
        self.assertEqual(first["count"], 4)
        with self.assertRaises(ValueError):
            final_state_identity({"components": 2})

    def test_profile_hash_selection_distinguishes_spine_and_grasu(self) -> None:
        contract = {
            "architecture_baselines": {
                "spine": {"sha256": "spine"},
                "grasu_regraph_k1": {
                    "profiles": {"connected_components": ["cc.json", "k1"]}
                },
            }
        }
        self.assertEqual(
            expected_profile_hash(contract, "spine", "connected_components"),
            "spine",
        )
        self.assertEqual(
            expected_profile_hash(
                contract, "grasu_regraph_k1", "connected_components"
            ),
            "k1",
        )

    def test_result_row_records_cycles_traffic_and_parallelism(self) -> None:
        case = SimpleNamespace(
            execution_id="run",
            dataset_id="graph",
            scenario="insert",
            system="grasu_regraph_k4_shared",
            graph={"vertices": 100, "records": 200},
            update={"records": 16, "user_mutations": 8},
        )
        result = {
            "cycles": 1500,
            "iterations": 2,
            "active_edges": 300,
            "backend_requests": 30,
            "backend_traffic": {
                "reads": {"bytes": 1024},
                "writes": {"bytes": 512},
            },
            "backend_submit_stalls": 7,
            "backend_response_queue_stalls": 3,
            "destination_partitions": 2,
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
        }
        manifest = {
            "profile_id": "k4-shared",
            "profile_sha256": "hash",
            "core_mhz": 150.0,
            "compute_pipelines": 4,
            "downstream_sharing": "shared",
            "dram": {
                "reads": 20,
                "writes": 10,
                "total_energy_pj": 42.0,
            },
        }
        row = result_row(case, result, manifest, wall_seconds=0.5)
        self.assertEqual(row["e2e_us"], 10.0)
        self.assertEqual(row["compute_pipelines"], 4)
        self.assertEqual(row["downstream_sharing"], "shared")
        self.assertEqual(row["read_bytes"], 1024)
        self.assertEqual(row["dram_energy_pj"], 42.0)

    def test_result_row_labels_r19_as_synthetic(self) -> None:
        case = SimpleNamespace(
            execution_id="run",
            dataset_id="rmat_19_32",
            scenario="insert",
            system="spine",
            algorithm="connected_components",
            batch_size=8,
            graph={"vertices": 4, "records": 6},
            update={"records": 2, "user_mutations": 1},
            source=0,
            algorithm_parameters={},
        )
        result = {
            "cycles": 10,
            "iterations": 1,
            "active_edges": 2,
            "backend_requests": 4,
            "backend_traffic": {
                "reads": {"bytes": 8},
                "writes": {"bytes": 8},
            },
            "destination_partitions": 1,
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
        }
        manifest = {
            "profile_id": "spine",
            "profile_sha256": "hash",
            "core_mhz": 150.0,
            "compute_pipelines": 1,
            "dram": {"reads": 2, "writes": 2, "total_energy_pj": 1.0},
        }
        row = result_row(case, result, manifest, wall_seconds=0.1)
        self.assertEqual(row["dataset_kind"], "synthetic")
        self.assertEqual(row["role"], "publication_scalability_endpoint")


if __name__ == "__main__":
    unittest.main()
