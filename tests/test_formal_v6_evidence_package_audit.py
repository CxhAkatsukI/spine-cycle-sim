from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_formal_v6_evidence_package.py"
SPEC = importlib.util.spec_from_file_location("formal_v6_evidence_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FormalV6EvidencePackageAuditTest(unittest.TestCase):
    def _fixture(self, directory: Path) -> dict[str, object]:
        algorithms = sorted(MODULE.REQUIRED_ALGORITHMS)
        datasets = ("au", "su", "wk")
        system_rows = []
        component_rows = []
        pair_rows = []
        correctness_rows = []
        for dataset in datasets:
            for algorithm in algorithms:
                group_id = f"{dataset}-{algorithm}"
                pair_rows.append(
                    {
                        "group_id": group_id,
                        "dataset_id": dataset,
                        "dataset_kind": "real",
                        "algorithm": algorithm,
                        "competitor": "grasu_regraph_k4_shared",
                    }
                )
                correctness_rows.append(
                    {
                        "group_id": group_id,
                        "complete_required_systems": "True",
                        "final_state_match": "True",
                        "missing_systems": "",
                    }
                )
                for system in ("spine", "grasu"):
                    execution_id = f"{group_id}-{system}"
                    system_rows.append({"execution_id": execution_id})
                    component_rows.append({"execution_id": execution_id})
        observed = len(system_rows)
        primary_summary = {
            "status": "PARTIAL",
            "observed_executions": observed,
            "expected_executions": observed + 1,
            "missing_execution_ids": ["pending"],
            "failed_correctness_groups": 0,
            "evidence_audit": {
                "all_observed_executions_audited": True,
                "individual_correctness_gates_passed": observed,
                "backend_arbitration_ledgers_closed": observed,
                "backend_traffic_ledgers_closed": observed,
                "dram_request_ledgers_closed": observed,
                "component_activity_executions": observed,
            },
        }
        update_rows = [
            {"scenario": scenario, "batch_size": str(batch)}
            for scenario, batch in sorted(MODULE.REQUIRED_UPDATE_GRID)
        ]
        rq3_coverage_rows = [
            {
                "case_class": case_class,
                "status": "ready",
                "eligible_executions": "1",
            }
            for case_class in MODULE.REQUIRED_RQ3_CLASSES
        ]
        rq3_regression_rows = [
            {"role": "all", "mechanism": mechanism, "r2": "0.995"}
            for mechanism in MODULE.REQUIRED_RQ3_REGRESSIONS
        ]
        for row in rq3_regression_rows:
            row.update({"samples": "5", "slope": "1.0"})
        rq3_summary = {
            "direct_ten_stage_rows": 5,
            "all_direct_ten_stage_ledgers_closed": True,
            "e2e_model": {"status": "fit", "full_rank": True},
        }
        rq3_e2e_metric_rows = [
            {
                "role": "real_trace_holdout",
                "samples": "30",
                "r2": "0.95",
                "median_ape_percent": "20.0",
                "mape_percent": "25.0",
                "max_ape_percent": "80.0",
            }
        ]
        artifacts = []
        for name in ("report.pdf", "figure.svg"):
            path = directory / name
            path.write_bytes(b"evidence")
            artifacts.append(path)
        return {
            "primary_summary": primary_summary,
            "system_rows": system_rows,
            "pair_rows": pair_rows,
            "correctness_rows": correctness_rows,
            "component_rows": component_rows,
            "update_rows": update_rows,
            "rq3_summary": rq3_summary,
            "rq3_coverage_rows": rq3_coverage_rows,
            "rq3_regression_rows": rq3_regression_rows,
            "rq3_e2e_metric_rows": rq3_e2e_metric_rows,
            "artifacts": artifacts,
        }

    def test_minimum_pass_does_not_hide_partial_full_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = MODULE.audit_evidence_package(
                **self._fixture(Path(temporary))
            )
        self.assertEqual(result["minimum_package_status"], "PASS")
        self.assertEqual(result["full_matrix_status"], "PARTIAL")

    def test_missing_component_activity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self._fixture(Path(temporary))
            fixture["component_rows"] = fixture["component_rows"][:-1]
            result = MODULE.audit_evidence_package(**fixture)
        self.assertFalse(
            result["gates"][
                "observed_correctness_memory_and_activity_ledgers_closed"
            ]
        )
        self.assertEqual(result["minimum_package_status"], "INCOMPLETE")

    def test_missing_algorithm_and_rq3_relation_fail_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self._fixture(Path(temporary))
            fixture["pair_rows"] = [
                row
                for row in fixture["pair_rows"]
                if not (
                    row["dataset_id"] == "wk"
                    and row["algorithm"] == "weighted_sssp"
                )
            ]
            fixture["rq3_regression_rows"] = fixture["rq3_regression_rows"][1:]
            result = MODULE.audit_evidence_package(**fixture)
        self.assertFalse(
            result["gates"][
                "three_algorithm_matrix_on_at_least_three_real_datasets"
            ]
        )
        self.assertFalse(
            result["gates"]["seven_rq3_mechanism_relations_are_reported"]
        )

    def test_real_holdout_and_ten_stage_gates_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self._fixture(Path(temporary))
            fixture["rq3_summary"]["all_direct_ten_stage_ledgers_closed"] = False
            fixture["rq3_e2e_metric_rows"][0]["samples"] = "29"
            result = MODULE.audit_evidence_package(**fixture)
        self.assertFalse(
            result["gates"]["five_rq3_direct_ten_stage_ledgers_close"]
        )
        self.assertFalse(
            result["gates"]["rq3_e2e_model_generalizes_to_30_real_holdouts"]
        )


if __name__ == "__main__":
    unittest.main()
