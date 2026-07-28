from __future__ import annotations

import unittest

from scripts.run_sst_connected_components import validate_result
from spine_cycle_sim.experiments.connected_components_workloads import (
    ReciprocalUpdateAnalysis,
)


class SstConnectedComponentsRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analysis = ReciprocalUpdateAnalysis(
            logical_user_mutations=1,
            effective_mutations=1,
            physical_records=2,
            insertions=1,
            deletions=0,
            zero_net=False,
            touched_vertices=(1, 2),
        )
        self.base = {
            "success": True,
            "algorithm_contract": "weakly_connected_min_vertex_reciprocal_v1",
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "correctness_mismatches": 0,
            "labels": [0, 0, 0, 3],
            "converged": True,
            "frontier_out_sizes": [1, 0],
            "update_mode": "insertion_incremental_repair",
            "logical_mutations": 1,
            "physical_update_records": 2,
            "initial_active_vertices": 2,
            "active_edges": 4,
            "active_edge_execution_ledger_match": True,
            "memory_locality_ledger_match": True,
        }

    def test_spine_admission_requires_exact_external_labels(self) -> None:
        result = dict(self.base, mode="spine_connected_components")
        checks = validate_result(
            result,
            architecture="spine",
            expected_labels=(0, 0, 0, 3),
            analysis=self.analysis,
            compute_pipelines=1,
            downstream_sharing="direct",
        )
        self.assertTrue(all(checks.values()))
        result["labels"] = [0, 0, 2, 3]
        self.assertFalse(
            validate_result(
                result,
                architecture="spine",
                expected_labels=(0, 0, 0, 3),
                analysis=self.analysis,
                compute_pipelines=1,
                downstream_sharing="direct",
            )["external_labels"]
        )

    def test_grasu_admission_checks_work_and_partition_ledgers(self) -> None:
        result = dict(
            self.base,
            mode="grasu_regraph_connected_components",
            conversion_cost_included=False,
            update_state_mismatches=0,
            compute_pipelines=4,
            downstream_sharing="direct",
            max_parallel_downstream_partitions=3,
            partition_passes=6,
            destination_partitions=3,
            iterations=2,
        )
        checks = validate_result(
            result,
            architecture="grasu",
            expected_labels=(0, 0, 0, 3),
            analysis=self.analysis,
            compute_pipelines=4,
            downstream_sharing="direct",
        )
        self.assertTrue(all(checks.values()))
        result["partition_passes"] = 5
        self.assertFalse(
            validate_result(
                result,
                architecture="grasu",
                expected_labels=(0, 0, 0, 3),
                analysis=self.analysis,
                compute_pipelines=4,
                downstream_sharing="direct",
            )["partition_work"]
        )

    def test_shared_downstream_requires_one_active_downstream(self) -> None:
        result = dict(
            self.base,
            mode="grasu_regraph_connected_components",
            conversion_cost_included=False,
            update_state_mismatches=0,
            compute_pipelines=4,
            downstream_sharing="shared",
            max_parallel_downstream_partitions=1,
            partition_passes=8,
            destination_partitions=4,
            iterations=2,
        )
        checks = validate_result(
            result,
            architecture="grasu",
            expected_labels=(0, 0, 0, 3),
            analysis=self.analysis,
            compute_pipelines=4,
            downstream_sharing="shared",
        )
        self.assertTrue(all(checks.values()))


if __name__ == "__main__":
    unittest.main()
