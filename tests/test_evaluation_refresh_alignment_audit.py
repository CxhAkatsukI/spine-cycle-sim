from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_evaluation_refresh_alignment import (
    DEFAULT_CALIBRATION_CONTRACT,
    build_audit,
    calibration_contract_status,
)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def write_complete_campaign(root: Path) -> Path:
    analysis = root / "analysis"
    write_json(
        analysis / "summary.json",
        {
            "status": "PASS",
            "observed_executions": 18,
            "expected_executions": 18,
            "missing_execution_ids": [],
        },
    )
    with (analysis / "pair_rows.csv").open(
        "w", encoding="utf-8", newline=""
    ) as sink:
        writer = csv.DictWriter(sink, fieldnames=["dataset_id", "algorithm"])
        writer.writeheader()
        for dataset in ("sx_askubuntu", "sx_superuser", "wiki_talk_temporal"):
            for algorithm in (
                "weighted_sssp",
                "connected_components",
                "thresholded_residual_pagerank",
            ):
                writer.writerow({"dataset_id": dataset, "algorithm": algorithm})
    return analysis


def write_current_fig9_package(root: Path) -> Path:
    analysis = root / "fig9_current"
    write_json(
        analysis / "manifest.json",
        {
            "status": "PASS_CURRENT_MODEL_DATA",
            "rows": 9,
            "expected_rows": 9,
        },
    )
    with (analysis / "pair_rows.csv").open(
        "w", encoding="utf-8", newline=""
    ) as sink:
        writer = csv.DictWriter(sink, fieldnames=["dataset_id", "algorithm"])
        writer.writeheader()
        for dataset in ("au", "su", "wk"):
            for algorithm in (
                "weighted_sssp",
                "connected_components",
                "thresholded_residual_pagerank",
            ):
                writer.writerow({"dataset_id": dataset, "algorithm": algorithm})
    return analysis


def write_calibration_manifests(root: Path) -> Path:
    calibration = root / "calibration"
    contract = calibration_contract_status(DEFAULT_CALIBRATION_CONTRACT)
    coverage_identity = []
    for pair in contract["expected_pairs"]:
        architecture, algorithm, profile_id = pair.split(":")
        coverage_identity.append(
            {
                "architecture": architecture,
                "algorithm": algorithm,
                "profile_id": profile_id,
            }
        )
    common = {
        "schema_version": 1,
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["sha256"],
        "status": "PASS",
        "parameters_frozen": True,
        "correctness_gate": "PASS",
        "workload_identity_pinned": True,
        "calibration_and_holdout_disjoint": True,
        "threshold_checks": {"all_pass": True},
    }
    total_coverage = [
        dict(row, calibration_cases=2, holdout_cases=2)
        for row in coverage_identity
    ]
    component_coverage = [
        dict(row, calibration_cases=2, holdout_cases=1)
        for row in coverage_identity
    ]
    ledger_coverage = [
        dict(row, validation_cases=1, ledger_closed=True)
        for row in coverage_identity
    ]
    write_json(
        calibration / "total_cycle_calibration.json",
        dict(common, gate_kind="total_cycle", coverage=total_coverage),
    )
    write_json(
        calibration / "component_cycle_calibration.json",
        dict(
            common,
            gate_kind="component_cycle",
            coverage=component_coverage,
            hardware_observation_scope="event_union_and_exposed_kernel_events",
        ),
    )
    write_json(
        calibration / "memory_ledger_validation.json",
        dict(
            common,
            gate_kind="memory_ledger",
            coverage=ledger_coverage,
            hardware_observation_scope="structural_simulator_ledger_only",
        ),
    )
    structural_coverage = []
    for row in coverage_identity:
        structural_coverage.append(
            dict(
                row,
                validation_cases=1,
                ledger_closed=row["architecture"] == "spine",
                hardware_counter_scope=(
                    "routed_iteration_task_edge_counters"
                    if row["architecture"] == "spine"
                    else "not_observable"
                ),
            )
        )
    write_json(
        calibration / "structural_work_validation.json",
        dict(
            common,
            gate_kind="structural_work",
            coverage=structural_coverage,
            hardware_observation_scope=(
                "Spine routed iteration/task/edge counters; G+R counters unavailable"
            ),
            grasu_regraph_hardware_counter_limitation_explicit=True,
        ),
    )
    return calibration


class EvaluationRefreshAlignmentAuditTests(unittest.TestCase):
    def test_archived_figures_keep_audit_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance = root / "provenance"
            write_json(provenance / "fig7.json", {"status": "PASS"})
            write_json(
                provenance / "fig8.json",
                {"status": "INTERIM_ARCHIVED_SIMULATOR_DATA"},
            )
            write_json(
                provenance / "fig9.json",
                {"status": "INTERIM_ARCHIVED_SIMULATOR_DATA"},
            )
            write_json(
                provenance / "fig10.json",
                {"status": "INTERIM_ARCHIVED_SIMULATOR_DATA"},
            )
            analysis = root / "analysis"
            write_json(
                analysis / "summary.json",
                {
                    "status": "PARTIAL",
                    "observed_executions": 10,
                    "expected_executions": 18,
                    "missing_execution_ids": ["missing"],
                },
            )
            with (analysis / "pair_rows.csv").open(
                "w", encoding="utf-8", newline=""
            ) as sink:
                writer = csv.DictWriter(
                    sink, fieldnames=["dataset_id", "algorithm"]
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "dataset_id": "sx_askubuntu",
                        "algorithm": "weighted_sssp",
                    }
                )

            audit = build_audit(root, analysis)

        self.assertEqual(audit["status"], "INCOMPLETE")
        self.assertTrue(audit["figures"]["fig7"]["aligned"])
        self.assertFalse(audit["figures"]["fig8"]["aligned"])
        self.assertFalse(audit["figures"]["fig9"]["aligned"])
        self.assertEqual(audit["campaign"]["pair_rows"], 1)
        self.assertFalse(audit["campaign"]["complete_for_fig9"])

    def test_current_model_statuses_without_fpga_calibration_are_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance = root / "provenance"
            statuses = {
                "fig7": "PASS",
                "fig8": "PASS_CURRENT_MODEL_DATA",
                "fig9": "PASS_CAMPAIGN_ANALYSIS",
                "fig10": "PASS_CURRENT_MODEL_DATA",
            }
            for figure, status in statuses.items():
                write_json(provenance / f"{figure}.json", {"status": status})
            analysis = write_complete_campaign(root)

            audit = build_audit(root, analysis)

        self.assertEqual(audit["status"], "INCOMPLETE")
        self.assertEqual(audit["campaign"]["pair_rows"], 9)
        self.assertFalse(audit["calibration"]["passed"])
        self.assertFalse(audit["figures"]["fig8"]["aligned"])

    def test_ready_requires_complete_calibration_and_holdout_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance = root / "provenance"
            statuses = {
                "fig7": "PASS",
                "fig8": "PASS_CURRENT_MODEL_DATA",
                "fig9": "PASS_CAMPAIGN_ANALYSIS",
                "fig10": "PASS_CURRENT_MODEL_DATA",
            }
            for figure, status in statuses.items():
                write_json(provenance / f"{figure}.json", {"status": status})
            analysis = write_complete_campaign(root)
            calibration = write_calibration_manifests(root)

            audit = build_audit(
                root,
                analysis,
                DEFAULT_CALIBRATION_CONTRACT,
                calibration,
            )

        self.assertEqual(audit["status"], "READY")
        self.assertTrue(audit["calibration"]["passed"])
        self.assertEqual(audit["next_actions"], [])

    def test_current_ledger_gated_fig9_package_can_be_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance = root / "provenance"
            statuses = {
                "fig7": "PASS",
                "fig8": "PASS_CURRENT_MODEL_DATA",
                "fig9": "PASS_CURRENT_MODEL_DATA",
                "fig10": "PASS_CURRENT_MODEL_DATA",
            }
            for figure, status in statuses.items():
                write_json(provenance / f"{figure}.json", {"status": status})
            analysis = write_current_fig9_package(root)
            calibration = write_calibration_manifests(root)

            audit = build_audit(
                root,
                analysis,
                DEFAULT_CALIBRATION_CONTRACT,
                calibration,
            )

        self.assertEqual(audit["status"], "READY")
        self.assertEqual(
            audit["campaign"]["evidence_kind"],
            "current_ledger_gated_fig9_package",
        )

    def test_missing_structural_work_manifest_blocks_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance = root / "provenance"
            for figure, status in {
                "fig7": "PASS",
                "fig8": "PASS_CURRENT_MODEL_DATA",
                "fig9": "PASS_CAMPAIGN_ANALYSIS",
                "fig10": "PASS_CURRENT_MODEL_DATA",
            }.items():
                write_json(provenance / f"{figure}.json", {"status": status})
            analysis = write_complete_campaign(root)
            calibration = write_calibration_manifests(root)
            (calibration / "structural_work_validation.json").unlink()

            audit = build_audit(
                root,
                analysis,
                DEFAULT_CALIBRATION_CONTRACT,
                calibration,
            )

        self.assertEqual(audit["status"], "INCOMPLETE")
        self.assertFalse(audit["calibration"]["manifests"]["structural_work"]["passed"])
        self.assertFalse(audit["figures"]["fig8"]["aligned"])
        self.assertFalse(audit["figures"]["fig9"]["aligned"])
        self.assertFalse(audit["figures"]["fig10"]["aligned"])


if __name__ == "__main__":
    unittest.main()
