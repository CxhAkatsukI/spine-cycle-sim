from __future__ import annotations

import copy
import unittest

from scripts.analyze_large_real_algorithm_results import analyze_payloads


def _manifest(records: int):
    return {
        "runs": [
            {
                "graph": {
                    "vertices": records // 4,
                    "records": records,
                    "sha256": f"graph-{records}",
                }
            }
        ]
    }


def _cc_summary(prefix: str):
    rows = []
    pairs = []
    for batch in (1, 8, 64, 512):
        run_id = f"{prefix}_u{batch}"
        for architecture, cycles in (("spine", 100), ("grasu", 200)):
            rows.append(
                {
                    "run_id": run_id,
                    "architecture": architecture,
                    "vertices": 100,
                    "initial_edges": 540000,
                    "logical_user_mutations": batch,
                    "initial_components": 10,
                    "final_components": 9,
                    "iterations": 2,
                    "active_edges": 20,
                    "cycles": cycles,
                    "read_bytes": 1000,
                    "write_bytes": 500,
                    "correctness_mismatches": 0,
                }
            )
        pairs.append(
            {
                "run_id": run_id,
                "performance_admitted": True,
                "spine_speedup_over_grasu": 2.0,
            }
        )
    return {
        "all_correct": True,
        "all_admission_checks_passed": True,
        "rows": rows,
        "pairs": pairs,
    }


def _residual_summary(prefix: str):
    runs = []
    pairs = []
    for batch in (1, 8, 64, 512):
        run_id = f"{prefix}_u{batch}"
        for architecture, cycles in (("spine", 100), ("grasu_regraph", 200)):
            runs.append(
                {
                    "run_id": run_id,
                    "architecture": architecture,
                    "vertices": 100,
                    "initial_edges": 540000,
                    "user_mutations": batch,
                    "iterations": 2,
                    "initial_active_vertices": 4,
                    "active_edges": 20,
                    "residual_linf": 5e-7,
                    "cycles": cycles,
                }
            )
        pairs.append(
            {
                "run_id": run_id,
                "user_mutations": batch,
                "iterations": 2,
                "correctness_admitted": True,
                "cross_system_frontiers_match": True,
                "cross_system_max_abs_rank_difference": 0.0,
                "cross_system_max_abs_residual_difference": 0.0,
                "spine_cycles": 100,
                "grasu_cycles": 200,
                "spine_speedup_over_grasu": 2.0,
                "spine_backend_bytes": 1000,
                "grasu_backend_bytes": 2000,
            }
        )
    return {"all_correct": True, "runs": runs, "pairs": pairs}


class LargeRealAlgorithmResultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.arguments = {
            "weighted_manifest": {
                "status": "PASS",
                "all_correct": True,
                "complete_matrix": True,
            },
            "weighted_rows": [
                {
                    "run_id": f"weighted_u{batch}",
                    "user_mutations": str(batch),
                    "spine_aligned_e2e_ms": "1",
                    "grasu_aligned_e2e_ms": "2",
                    "spine_speedup_over_grasu_e2e": "2",
                    "cross_system_distances_match": "True",
                }
                for batch in (8, 64, 4096)
            ],
            "weighted_input": _manifest(540000),
            "cc_gate": _cc_summary("gate"),
            "residual_gate": _residual_summary("gate"),
            "cc_full": _cc_summary("full"),
            "residual_full": _residual_summary("full"),
            "gate_manifest": _manifest(540000),
            "full_manifest": _manifest(903774),
        }

    def test_analysis_accepts_complete_correct_matrices(self) -> None:
        report = analyze_payloads(**self.arguments)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(all(report["checks"].values()))
        self.assertEqual(
            report["connected_components"]["full_graph"]["records"], 903774
        )

    def test_analysis_rejects_cross_system_cc_work_mismatch(self) -> None:
        arguments = copy.deepcopy(self.arguments)
        arguments["cc_gate"]["rows"][0]["active_edges"] += 1
        with self.assertRaisesRegex(ValueError, "active_edges"):
            analyze_payloads(**arguments)

    def test_analysis_rejects_residual_threshold_violation(self) -> None:
        arguments = copy.deepcopy(self.arguments)
        arguments["residual_full"]["runs"][0]["residual_linf"] = 2e-6
        with self.assertRaisesRegex(ValueError, "threshold"):
            analyze_payloads(**arguments)


if __name__ == "__main__":
    unittest.main()
