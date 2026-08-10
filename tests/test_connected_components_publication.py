from __future__ import annotations

import copy
import unittest

from scripts.analyze_connected_components_publication import (
    SCALABILITY_ID,
    SCREENING_IDS,
    analyze_payloads,
)


def _row(run_id: str, architecture: str, pipelines: int, sharing: str, cycles: int):
    parallel = pipelines if architecture == "grasu" else 1
    downstream = parallel if sharing == "direct" else 1
    return {
        "run_id": run_id,
        "architecture": architecture,
        "vertices": 262144,
        "initial_edges": 8192,
        "logical_user_mutations": 4,
        "effective_mutations": 4,
        "physical_records": 8,
        "initial_components": 100,
        "final_components": 96,
        "iterations": 2,
        "active_edges": 48,
        "compute_pipelines": pipelines,
        "downstream_sharing": sharing,
        "max_parallel_partitions": parallel,
        "max_parallel_downstream_partitions": downstream,
        "cycles": cycles,
        "backend_requests": 1000,
        "read_bytes": 2000,
        "write_bytes": 3000,
        "correctness_mismatches": 0,
        "performance_admitted": True,
        "source_revision": "source",
        "workload_sha256": "workload",
        "update_sha256": "update",
        "sst_plugin_sha256": "plugin",
    }


def _payload(rows):
    return {
        "all_correct": True,
        "all_admission_checks_passed": True,
        "rows": rows,
    }


class ConnectedComponentsPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        screening = []
        for run_id in SCREENING_IDS:
            screening.extend(
                (
                    _row(run_id, "spine", 1, "native", 100),
                    _row(run_id, "grasu", 1, "direct", 200),
                )
            )
        self.payloads = {
            "k1": _payload(screening),
            "p4_k1": _payload(
                [
                    _row(SCALABILITY_ID, "spine", 1, "native", 100),
                    _row(SCALABILITY_ID, "grasu", 1, "direct", 1600),
                ]
            ),
            "p4_direct_k4": _payload(
                [_row(SCALABILITY_ID, "grasu", 4, "direct", 500)]
            ),
            "p4_shared_k4": _payload(
                [_row(SCALABILITY_ID, "grasu", 4, "shared", 520)]
            ),
        }

    def test_analysis_reports_screening_and_scalability(self) -> None:
        analysis = analyze_payloads(self.payloads)
        self.assertEqual(analysis["status"], "PASS")
        self.assertEqual(len(analysis["screening_pairs"]), 4)
        self.assertAlmostEqual(
            analysis["scalability_metrics"]["k1_to_direct_k4_speedup"], 3.2
        )

    def test_analysis_rejects_traffic_change(self) -> None:
        payloads = copy.deepcopy(self.payloads)
        payloads["p4_shared_k4"]["rows"][0]["read_bytes"] += 1
        with self.assertRaisesRegex(ValueError, "traffic_conservation"):
            analyze_payloads(payloads)

    def test_analysis_rejects_wrong_shared_topology(self) -> None:
        payloads = copy.deepcopy(self.payloads)
        payloads["p4_shared_k4"]["rows"][0][
            "max_parallel_downstream_partitions"
        ] = 4
        with self.assertRaisesRegex(ValueError, "parallel_topology"):
            analyze_payloads(payloads)


if __name__ == "__main__":
    unittest.main()
