from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.publication_analysis import (
    analyze_publication_case_results,
)


def case_result(system: str, cycles: int, *, execution_id: str | None = None) -> dict:
    execution_id = execution_id or f"execution_{system}"
    return {
        "schema_version": 1,
        "status": "pass",
        "case": {
            "execution_id": execution_id,
            "dataset_id": "graph",
            "system": system,
            "algorithm": "weighted_sssp",
            "scenario": "insert",
            "batch_size": 8,
            "graph": {
                "sha256": "1" * 64,
                "vertices": 4,
                "records": 6,
            },
            "update": {
                "sha256": "2" * 64,
                "user_mutations": 8,
                "physical_records": 8,
            },
            "source": 0,
            "algorithm_parameters": {"source_cohort": "default"},
        },
        "logical_views": ["main_e2e"],
        "row": {
            "run_id": execution_id,
            "system": system,
            "dataset_kind": "real",
            "role": "publication_large_graph",
            "cycles": cycles,
            "clock_mhz": 150.0,
            "backend_requests": 12,
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "dram_energy_pj": float(cycles),
            "host_wall_seconds": 1.0,
        },
        "final_state": {
            "field": "distances",
            "count": 4,
            "sha256": "3" * 64,
        },
        "scalar_metrics": {"update_cycles": 100},
        "backend_arbitration": {"ledger_closed": True},
        "backend_traffic": {
            "combined": {
                "requests": 12,
                "contiguous_requests": 8,
                "discontinuous_requests": 4,
            },
            "reads": {"bytes": 512},
            "writes": {"bytes": 128},
        },
        "dram": {"reads": 8, "writes": 4},
        "plugin_sha256": "a" * 64,
        "admission": {"child_returncode": 0, "parent_checks": {"all": True}},
    }


def attach_raw_result(result: dict, path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="ascii")
    result["raw_result_path"] = str(path)
    result["raw_result_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


class PublicationAnalysisTests(unittest.TestCase):
    def test_complete_triplet_emits_two_correct_pairs(self) -> None:
        results = [
            case_result("spine", 100),
            case_result("grasu_regraph_k1", 400),
            case_result("grasu_regraph_k4_shared", 250),
        ]
        results[-1]["row"]["system"] = "grasu_regraph"
        analysis = analyze_publication_case_results(
            results,
            expected_execution_ids={row["case"]["execution_id"] for row in results},
            require_complete=True,
        )
        self.assertEqual(analysis["status"], "PASS")
        self.assertEqual(analysis["complete_triplets"], 1)
        self.assertEqual(len(analysis["pair_rows"]), 2)
        speedups = {
            row["competitor"]: row["spine_speedup"]
            for row in analysis["pair_rows"]
        }
        self.assertEqual(speedups["grasu_regraph_k1"], 4.0)
        self.assertEqual(speedups["grasu_regraph_k4_shared"], 2.5)

    def test_cross_system_final_state_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spine = case_result("spine", 100)
            competitor = case_result("grasu_regraph_k1", 400)
            competitor["final_state"]["sha256"] = "4" * 64
            attach_raw_result(
                spine,
                Path(temporary) / "spine.json",
                {"final_values": [0, 1, 2, 3]},
            )
            attach_raw_result(
                competitor,
                Path(temporary) / "competitor.json",
                {"distances_external": [0, 1, 9, 3]},
            )
            with self.assertRaisesRegex(ValueError, "final state mismatch"):
                analyze_publication_case_results([spine, competitor])

    def test_float_external_vectors_use_explicit_tolerance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spine = case_result("spine", 100)
            competitor = case_result("grasu_regraph_k1", 400)
            for result in (spine, competitor):
                result["case"]["algorithm"] = "full_pagerank"
                result["case"]["algorithm_parameters"] = {
                    "iterations": 3,
                    "damping": 0.85,
                }
            competitor["final_state"]["sha256"] = "4" * 64
            attach_raw_result(
                spine,
                Path(temporary) / "spine.json",
                {"ranks": [0.1, 0.2, 0.3, 0.4]},
            )
            attach_raw_result(
                competitor,
                Path(temporary) / "competitor.json",
                {
                    "ranks": [0.4, 0.3, 0.2, 0.1],
                    "ranks_external": [0.1, 0.2 + 1.0e-10, 0.3, 0.4],
                },
            )
            analysis = analyze_publication_case_results([spine, competitor])
            group = analysis["correctness_groups"][0]
            self.assertTrue(group["final_state_match"])
            self.assertFalse(group["final_state_exact_match"])
            self.assertLess(group["cross_system_max_abs_error"], 1.0e-6)

    def test_duplicate_execution_must_keep_scientific_result(self) -> None:
        first = case_result("spine", 100, execution_id="same")
        duplicate = deepcopy(first)
        duplicate["row"]["host_wall_seconds"] = 2.0
        duplicate["scalar_metrics"]["sst_host_wall_seconds"] = 3.0
        analysis = analyze_publication_case_results([first, duplicate])
        self.assertEqual(analysis["observed_executions"], 1)
        self.assertEqual(analysis["duplicate_executions"], 1)
        self.assertEqual(analysis["system_rows"][0]["host_wall_seconds"], 1.0)
        changed = deepcopy(first)
        changed["row"]["cycles"] = 101
        with self.assertRaisesRegex(ValueError, "changed scientific result"):
            analyze_publication_case_results([first, changed])

    def test_incomplete_expected_set_is_partial_or_fail_closed(self) -> None:
        result = case_result("spine", 100)
        analysis = analyze_publication_case_results(
            [result], expected_execution_ids={result["case"]["execution_id"], "missing"}
        )
        self.assertEqual(analysis["status"], "PARTIAL")
        self.assertEqual(analysis["missing_execution_ids"], ["missing"])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            analyze_publication_case_results(
                [result],
                expected_execution_ids={result["case"]["execution_id"], "missing"},
                require_complete=True,
            )

    def test_normalization_uses_executed_traffic_and_update_cycles(self) -> None:
        result = case_result("spine", 300)
        result["scalar_metrics"] = {"maintenance_cycles": 75}
        analysis = analyze_publication_case_results([result])
        row = analysis["system_rows"][0]
        self.assertEqual(row["update_cycles"], 75)
        self.assertAlmostEqual(row["sequential_request_fraction"], 2.0 / 3.0)
        self.assertEqual(row["read_bytes"] + row["write_bytes"], 640)


if __name__ == "__main__":
    unittest.main()
