#!/usr/bin/env python3
"""Fail closed on the formal-v6 first-evidence-package requirements."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / "docs" / "paper" / "data" / "formal_v6_primary"
RQ3 = ROOT / "docs" / "paper" / "data" / "rq3"

REQUIRED_ALGORITHMS = {
    "weighted_sssp",
    "connected_components",
    "thresholded_residual_pagerank",
}
REQUIRED_UPDATE_GRID = {
    (scenario, batch)
    for scenario in ("insert", "delete", "weight_change")
    for batch in (1, 8, 64)
}
REQUIRED_UPDATE_SCALING_GRID = {
    ("insert", batch) for batch in (64, 1_024, 16_384, 131_072)
}
REQUIRED_RQ3_CLASSES = {
    "zero_net",
    "shallow_insertion",
    "deep_carry",
    "pagerank_correction",
    "deletion_fallback",
}
REQUIRED_RQ3_REGRESSIONS = {
    "sort_frontend",
    "carry",
    "directory",
    "physical_resolve_apply",
    "seed",
    "switch",
    "drain",
}
DEFAULT_ARTIFACTS = (
    ROOT / "docs" / "paper" / "formal_v6_primary_results.pdf",
    ROOT / "docs" / "evidence" / "formal_v6_r19_k4_preflight_20260730.json",
    ROOT
    / "docs"
    / "evidence"
    / "formal_v6_large_sssp_runtime_projection_20260730.json",
    ROOT
    / "docs"
    / "paper"
    / "data"
    / "formal_v6_primary"
    / "wall_time_feasibility.json",
    ROOT / "docs" / "figures" / "formal_v6_primary_ratios.svg",
    ROOT / "docs" / "figures" / "formal_v6_memory_locality.svg",
    ROOT / "docs" / "figures" / "formal_v6_update_throughput.svg",
    ROOT / "docs" / "figures" / "rq3_latency_breakdown.svg",
    ROOT / "docs" / "figures" / "rq3_work_correlations.svg",
    ROOT / "docs" / "figures" / "rq3_e2e_cost_model.svg",
    ROOT / "docs" / "figures" / "formal_v7_workload_energy.svg",
    ROOT / "docs" / "paper" / "data" / "workload_energy" / "workload_energy.json",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _true(value: object) -> bool:
    return str(value).strip().lower() == "true"


def _execution_ids(rows: Iterable[Mapping[str, object]]) -> set[str]:
    return {
        str(row.get("execution_id", "")).strip()
        for row in rows
        if str(row.get("execution_id", "")).strip()
    }


def audit_evidence_package(
    *,
    primary_summary: Mapping[str, Any],
    system_rows: Sequence[Mapping[str, object]],
    pair_rows: Sequence[Mapping[str, object]],
    correctness_rows: Sequence[Mapping[str, object]],
    component_rows: Sequence[Mapping[str, object]],
    update_rows: Sequence[Mapping[str, object]],
    operation_update_rows: Sequence[Mapping[str, object]],
    rq3_summary: Mapping[str, Any],
    rq3_coverage_rows: Sequence[Mapping[str, object]],
    rq3_regression_rows: Sequence[Mapping[str, object]],
    rq3_e2e_metric_rows: Sequence[Mapping[str, object]],
    artifacts: Sequence[Path],
    minimum_real_datasets: int = 3,
    minimum_real_holdout_rows: int = 30,
    minimum_e2e_r2: float = 0.90,
    maximum_e2e_median_ape_percent: float = 50.0,
    audit_id: str = "formal_v6_first_evidence_package_v1",
) -> dict[str, Any]:
    if not audit_id:
        raise ValueError("audit_id must be nonempty")
    observed = int(primary_summary.get("observed_executions", 0))
    evidence = primary_summary.get("evidence_audit", {})
    if not isinstance(evidence, Mapping):
        evidence = {}
    system_execution_ids = _execution_ids(system_rows)
    activity_execution_ids = _execution_ids(component_rows)
    ledger_fields = (
        "individual_correctness_gates_passed",
        "backend_arbitration_ledgers_closed",
        "backend_traffic_ledgers_closed",
        "dram_request_ledgers_closed",
        "component_activity_executions",
    )
    ledger_counts = {
        field: int(evidence.get(field, -1)) for field in ledger_fields
    }
    observed_evidence_closed = (
        observed > 0
        and _true(evidence.get("all_observed_executions_audited", False))
        and len(system_execution_ids) == observed
        and activity_execution_ids == system_execution_ids
        and all(value == observed for value in ledger_counts.values())
    )

    complete_correctness_groups = {
        str(row.get("group_id", ""))
        for row in correctness_rows
        if _true(row.get("complete_required_systems", False))
        and _true(row.get("final_state_match", False))
        and str(row.get("missing_systems", "")) == ""
    }
    pair_group_ids = {
        str(row.get("group_id", "")) for row in pair_rows
    }
    correctness_closed = (
        int(primary_summary.get("failed_correctness_groups", -1)) == 0
        and bool(pair_group_ids)
        and pair_group_ids <= complete_correctness_groups
    )

    algorithms_by_dataset: dict[str, set[str]] = {}
    for row in pair_rows:
        if str(row.get("dataset_kind", "")) != "real":
            continue
        if str(row.get("competitor", "")) != "grasu_regraph_k4_shared":
            continue
        algorithms_by_dataset.setdefault(
            str(row.get("dataset_id", "")), set()
        ).add(str(row.get("algorithm", "")))
    complete_real_datasets = sorted(
        dataset
        for dataset, algorithms in algorithms_by_dataset.items()
        if REQUIRED_ALGORITHMS <= algorithms
    )
    three_algorithm_matrix = len(complete_real_datasets) >= minimum_real_datasets

    observed_update_scaling_grid = {
        (str(row.get("scenario", "")), int(row.get("batch_size", -1)))
        for row in update_rows
    }
    update_scaling = REQUIRED_UPDATE_SCALING_GRID <= observed_update_scaling_grid
    observed_update_grid = {
        (str(row.get("scenario", "")), int(row.get("batch_size", -1)))
        for row in operation_update_rows
    }
    update_matrix = REQUIRED_UPDATE_GRID <= observed_update_grid

    ready_rq3_classes = {
        str(row.get("case_class", ""))
        for row in rq3_coverage_rows
        if str(row.get("status", "")) == "ready"
        and int(row.get("eligible_executions", 0)) > 0
    }
    rq3_classes = REQUIRED_RQ3_CLASSES <= ready_rq3_classes

    headline_rows = {
        str(row.get("mechanism", "")): row
        for row in rq3_regression_rows
        if str(row.get("role", "")) == "all"
        and str(row.get("mechanism", "")) in REQUIRED_RQ3_REGRESSIONS
    }
    rq3_regressions = set(headline_rows) == REQUIRED_RQ3_REGRESSIONS and all(
        int(row.get("samples", 0)) >= 2
        and str(row.get("slope", "")) != ""
        and str(row.get("r2", "")) != ""
        for row in headline_rows.values()
    )
    headline_r2 = {
        mechanism: float(row["r2"])
        for mechanism, row in headline_rows.items()
        if str(row.get("r2", "")) != ""
    }
    rq3_ten_stage = (
        int(rq3_summary.get("direct_ten_stage_rows", 0))
        >= len(REQUIRED_RQ3_CLASSES)
        and _true(rq3_summary.get("all_direct_ten_stage_ledgers_closed", False))
    )
    real_holdout_rows = [
        row
        for row in rq3_e2e_metric_rows
        if str(row.get("role", "")) == "real_trace_holdout"
    ]
    real_holdout = real_holdout_rows[0] if len(real_holdout_rows) == 1 else {}
    rq3_e2e_holdout = (
        int(real_holdout.get("samples", 0)) >= minimum_real_holdout_rows
        and str(real_holdout.get("r2", "")) != ""
        and float(real_holdout.get("r2", 0.0)) >= minimum_e2e_r2
        and str(real_holdout.get("median_ape_percent", "")) != ""
        and float(real_holdout.get("median_ape_percent", float("inf")))
        <= maximum_e2e_median_ape_percent
        and rq3_summary.get("e2e_model", {}).get("status") == "fit"
        and _true(rq3_summary.get("e2e_model", {}).get("full_rank", False))
    )

    artifact_status: dict[str, bool] = {}
    for path in artifacts:
        resolved = path.resolve()
        try:
            label = str(resolved.relative_to(ROOT))
        except ValueError:
            label = str(resolved)
        artifact_status[label] = resolved.is_file() and resolved.stat().st_size > 0
    reproducible_artifacts = bool(artifact_status) and all(artifact_status.values())

    gates = {
        "observed_correctness_memory_and_activity_ledgers_closed": observed_evidence_closed,
        "cross_system_final_states_match_for_every_pair": correctness_closed,
        "three_algorithm_matrix_on_at_least_three_real_datasets": three_algorithm_matrix,
        "insert_delete_weight_change_batches_1_8_64_complete": update_matrix,
        "insertion_batches_64_1024_16384_131072_complete": update_scaling,
        "five_rq3_representative_classes_ready": rq3_classes,
        "five_rq3_direct_ten_stage_ledgers_close": rq3_ten_stage,
        "seven_rq3_mechanism_relations_are_reported": rq3_regressions,
        "rq3_e2e_model_generalizes_to_30_real_holdouts": rq3_e2e_holdout,
        "pdf_and_required_vector_figures_exist": reproducible_artifacts,
    }
    minimum_status = "PASS" if all(gates.values()) else "INCOMPLETE"
    missing_execution_ids = list(primary_summary.get("missing_execution_ids", []))
    full_matrix_status = (
        "PASS"
        if primary_summary.get("status") == "PASS" and not missing_execution_ids
        else "PARTIAL"
    )
    return {
        "schema_version": 1,
        "audit_id": audit_id,
        "minimum_package_status": minimum_status,
        "full_matrix_status": full_matrix_status,
        "gates": gates,
        "coverage": {
            "observed_executions": observed,
            "expected_executions": int(
                primary_summary.get("expected_executions", 0)
            ),
            "missing_execution_ids": missing_execution_ids,
            "complete_real_three_algorithm_datasets": complete_real_datasets,
            "required_algorithms": sorted(REQUIRED_ALGORITHMS),
            "observed_update_grid": [
                {"scenario": scenario, "batch_size": batch}
                for scenario, batch in sorted(observed_update_grid)
            ],
            "observed_update_scaling_grid": [
                {"scenario": scenario, "batch_size": batch}
                for scenario, batch in sorted(observed_update_scaling_grid)
            ],
            "ready_rq3_classes": sorted(ready_rq3_classes),
            "headline_rq3_r2": headline_r2,
            "direct_ten_stage_rows": int(
                rq3_summary.get("direct_ten_stage_rows", 0)
            ),
            "real_trace_holdout": dict(real_holdout),
            "component_activity_rows": len(component_rows),
        },
        "artifacts": artifact_status,
        "claim_boundary": (
            "PASS means the frozen first evidence package is internally complete; "
            "it does not turn a PARTIAL 36-execution matrix into a complete matrix."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-summary", type=Path, default=PRIMARY / "summary.json")
    parser.add_argument("--system-rows", type=Path, default=PRIMARY / "system_rows.csv")
    parser.add_argument("--pair-rows", type=Path, default=PRIMARY / "pairs.csv")
    parser.add_argument(
        "--correctness-rows", type=Path, default=PRIMARY / "correctness_groups.csv"
    )
    parser.add_argument(
        "--component-rows", type=Path, default=PRIMARY / "component_activity.csv"
    )
    parser.add_argument("--update-rows", type=Path, default=PRIMARY / "update_pairs.csv")
    parser.add_argument(
        "--operation-update-rows",
        type=Path,
        default=PRIMARY / "update_operation_pairs.csv",
    )
    parser.add_argument(
        "--rq3-coverage", type=Path, default=RQ3 / "rq3_coverage_rows.csv"
    )
    parser.add_argument(
        "--rq3-regressions", type=Path, default=RQ3 / "rq3_regression_rows.csv"
    )
    parser.add_argument("--rq3-summary", type=Path, default=RQ3 / "rq3_summary.json")
    parser.add_argument(
        "--rq3-e2e-metrics", type=Path, default=RQ3 / "rq3_e2e_metric_rows.csv"
    )
    parser.add_argument("--artifact", type=Path, action="append")
    parser.add_argument(
        "--out", type=Path, default=PRIMARY / "evidence_package_audit.json"
    )
    parser.add_argument("--require-full", action="store_true")
    parser.add_argument(
        "--audit-id", default="formal_v6_first_evidence_package_v1"
    )
    args = parser.parse_args()

    result = audit_evidence_package(
        primary_summary=_read_json(args.primary_summary),
        system_rows=_read_csv(args.system_rows),
        pair_rows=_read_csv(args.pair_rows),
        correctness_rows=_read_csv(args.correctness_rows),
        component_rows=_read_csv(args.component_rows),
        update_rows=_read_csv(args.update_rows),
        operation_update_rows=_read_csv(args.operation_update_rows),
        rq3_summary=_read_json(args.rq3_summary),
        rq3_coverage_rows=_read_csv(args.rq3_coverage),
        rq3_regression_rows=_read_csv(args.rq3_regressions),
        rq3_e2e_metric_rows=_read_csv(args.rq3_e2e_metrics),
        artifacts=tuple(args.artifact or DEFAULT_ARTIFACTS),
        audit_id=args.audit_id,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="ascii")
    print(rendered, end="")
    if result["minimum_package_status"] != "PASS":
        return 1
    if args.require_full and result["full_matrix_status"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
