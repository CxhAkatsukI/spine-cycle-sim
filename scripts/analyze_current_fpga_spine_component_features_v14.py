#!/usr/bin/env python3
"""Apply frozen Spine v14 component models to independent holdout datasets."""

from __future__ import annotations

import argparse
import csv
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import statistics
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_current_fpga_components import (  # noqa: E402
    discover_hardware_logs,
    load_admitted_result,
    memory_ledger_row,
    run_directory,
    spine_structural_work_row,
    unique_prefixed_record,
)
from scripts.freeze_current_fpga_spine_component_features_v14 import (  # noqa: E402
    calibration_root,
    component_feature_record,
    read_json,
    sha256_file,
    write_json,
)
from spine_cycle_sim.calibration.current_fpga import (  # noqa: E402
    SpineComponentFeatureModel,
    absolute_error_percent,
    spearman_rank_correlation,
    spine_component_feature_prediction_rows,
)


DEFAULT_CONTRACT = (
    ROOT / "configs/contracts/current_fpga_spine_component_features_v14.json"
)
DEFAULT_CASES = ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v7.json"
DEFAULT_FROZEN = (
    ROOT
    / "docs/evaluation_refresh_20260810/calibration_v14_frozen"
    / "frozen_spine_component_feature_models.json"
)
DEFAULT_V12_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_20260812"
)
DEFAULT_V13_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v13_20260812"
)
DEFAULT_HOLDOUT_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v14_20260812"
)
DEFAULT_HARDWARE_ROOT = Path(
    "/home/chuxiao/grasu-regraph-integration/docs/evidence/sharded_k4_fullgraph_20260806"
)
DEFAULT_OUT = ROOT / "docs/evaluation_refresh_20260810/calibration_v14_holdout"


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as sink:
        writer = csv.DictWriter(
            sink, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def dataclass_from_dict(cls: type, payload: dict[str, Any]):
    names = {field.name for field in fields(cls)}
    return cls(**{name: payload[name] for name in names})


def prediction_summaries(
    rows: list[dict[str, object]], role: str
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    total: list[dict[str, object]] = []
    component: list[dict[str, object]] = []
    algorithms = sorted({str(row["algorithm"]) for row in rows})
    for algorithm in algorithms:
        group = [
            row
            for row in rows
            if row["algorithm"] == algorithm and row["role"] == role
        ]
        if not group:
            continue
        total_errors = [float(row["total_absolute_error_percent"]) for row in group]
        total.append(
            {
                "algorithm": algorithm,
                "role": role,
                "cases": len(group),
                "median_absolute_error_percent": statistics.median(total_errors),
                "max_absolute_error_percent": max(total_errors),
                "workload_rank_spearman": (
                    spearman_rank_correlation(
                        [float(row["predicted_total_cycles"]) for row in group],
                        [float(row["hardware_total_cycles"]) for row in group],
                    )
                    if len(group) >= 2
                    else 0.0
                ),
            }
        )
        for name in ("maintenance", "reader", "compute", "iterative_span"):
            if name != "maintenance" and not any(int(row["rounds"]) for row in group):
                continue
            errors = [
                float(row[f"{name}_absolute_error_percent"]) for row in group
            ]
            component.append(
                {
                    "algorithm": algorithm,
                    "component": name,
                    "role": role,
                    "cases": len(group),
                    "median_absolute_error_percent": statistics.median(errors),
                    "max_absolute_error_percent": max(errors),
                }
            )
    return total, component


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--frozen-model", type=Path, default=DEFAULT_FROZEN)
    parser.add_argument("--v12-root", type=Path, default=DEFAULT_V12_ROOT)
    parser.add_argument("--v13-root", type=Path, default=DEFAULT_V13_ROOT)
    parser.add_argument("--holdout-root", type=Path, default=DEFAULT_HOLDOUT_ROOT)
    parser.add_argument("--hardware-root", type=Path, default=DEFAULT_HARDWARE_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    contract_path = args.contract.resolve()
    frozen_path = args.frozen_model.resolve()
    contract = read_json(contract_path)
    cases = read_json(args.cases.resolve())
    frozen = read_json(frozen_path)
    if frozen.get("status") != "FROZEN_BEFORE_HOLDOUT":
        raise ValueError("model is not a pre-holdout freeze")
    if frozen.get("contract_id") != contract["contract_id"]:
        raise ValueError("frozen model and contract differ")
    if frozen.get("holdout_used_for_fit") is not False:
        raise ValueError("frozen model used holdout data")
    plugin = ROOT / contract["simulator_plugin"]["path"]
    if sha256_file(plugin) != contract["simulator_plugin"]["sha256"]:
        raise ValueError("immutable simulator plugin hash mismatch")

    models = {
        algorithm: dataclass_from_dict(SpineComponentFeatureModel, payload)
        for algorithm, payload in frozen["models"].items()
    }
    roles = {
        dataset: role
        for role in ("calibration", "holdout")
        for dataset in contract["roles"][role]
    }
    profile_paths = {
        entry["profile_id"]: ROOT / entry["path"]
        for entry in read_json(
            ROOT / "configs/contracts/evaluation_refresh_fpga_calibration_v8.json"
        )["architecture_profiles"]
        if entry["architecture"] == "spine"
    }
    clock_mhz = float(contract["clock_mhz"])
    records_by_algorithm = {algorithm: [] for algorithm in models}
    ledger_rows: list[dict[str, object]] = []
    structural_rows: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    missing: list[str] = []

    for algorithm, algorithm_spec in cases["algorithms"].items():
        for dataset, role in roles.items():
            root = (
                calibration_root(
                    dataset, args.v12_root.resolve(), args.v13_root.resolve()
                )
                if role == "calibration"
                else args.holdout_root.resolve()
            )
            run_dir = run_directory(root, algorithm_spec, dataset, "spine")
            try:
                result, result_path, manifest_path = load_admitted_result(run_dir)
            except FileNotFoundError:
                missing.append(f"{algorithm}:{dataset}")
                if args.allow_partial:
                    continue
                raise
            manifest = read_json(manifest_path)
            if manifest.get("sst_plugin_sha256") != contract["simulator_plugin"]["sha256"]:
                raise ValueError(f"plugin mismatch: {algorithm}:{dataset}")
            logs = discover_hardware_logs(
                args.hardware_root.resolve(), algorithm_spec, dataset, "spine"
            )
            if len(logs) < 3:
                raise ValueError(f"three routed logs required: {algorithm}:{dataset}")
            hardware = [unique_prefixed_record(path, "SPINE_HW_TIMING") for path in logs]
            records_by_algorithm[algorithm].append(
                component_feature_record(
                    algorithm=algorithm,
                    profile_id=contract["profiles"][algorithm],
                    dataset=dataset,
                    role=role,
                    result=result,
                    hardware=hardware,
                    clock_mhz=clock_mhz,
                )
            )
            structural = spine_structural_work_row(
                algorithm,
                dataset,
                role,
                result,
                result_path,
                logs,
                hardware,
            )
            structural["profile_id"] = contract["profiles"][algorithm]
            structural_rows.append(structural)
            profile = read_json(profile_paths[contract["profiles"][algorithm]])[
                "parameters"
            ]
            ledger = memory_ledger_row(
                "spine", algorithm, dataset, role, result, result_path, profile
            )
            ledger["profile_id"] = contract["profiles"][algorithm]
            ledger_rows.append(ledger)
            evidence.append(
                {
                    "algorithm": algorithm,
                    "dataset": dataset,
                    "role": role,
                    "simulator_result": str(result_path.resolve()),
                    "simulator_result_sha256": sha256_file(result_path),
                    "simulator_manifest": str(manifest_path.resolve()),
                    "simulator_manifest_sha256": sha256_file(manifest_path),
                    "hardware_logs": [str(path) for path in logs],
                    "hardware_log_sha256": [sha256_file(path) for path in logs],
                }
            )

    prediction_rows: list[dict[str, object]] = []
    for algorithm, records in records_by_algorithm.items():
        prediction_rows.extend(
            spine_component_feature_prediction_rows(records, models[algorithm])
        )
    calibration_total, calibration_components = prediction_summaries(
        prediction_rows, "calibration"
    )
    holdout_total, holdout_components = prediction_summaries(
        prediction_rows, "holdout"
    )

    status = "INCOMPLETE" if missing else "PASS"
    if not missing:
        if any(row["status"] != "PASS" for row in ledger_rows + structural_rows):
            status = "FAIL"
        thresholds = contract["thresholds"]
        if any(
            float(row["median_absolute_error_percent"])
            > thresholds["holdout_total_median_absolute_error_percent_max"]
            or float(row["max_absolute_error_percent"])
            > thresholds["holdout_total_absolute_error_percent_max"]
            or float(row["workload_rank_spearman"])
            < thresholds["workload_rank_spearman_min"]
            for row in holdout_total
        ):
            status = "FAIL"
        if any(
            float(row["median_absolute_error_percent"])
            > thresholds["holdout_component_median_absolute_error_percent_max"]
            or float(row["max_absolute_error_percent"])
            > thresholds["holdout_component_absolute_error_percent_max"]
            for row in holdout_components
        ):
            status = "FAIL"

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "prediction_rows.csv", prediction_rows)
    write_csv(args.out_dir / "calibration_total_summary.csv", calibration_total)
    write_csv(
        args.out_dir / "calibration_component_summary.csv", calibration_components
    )
    write_csv(args.out_dir / "holdout_total_summary.csv", holdout_total)
    write_csv(args.out_dir / "holdout_component_summary.csv", holdout_components)
    write_json(
        args.out_dir / "memory_ledger_validation.json",
        {"status": status, "rows": ledger_rows},
    )
    write_json(
        args.out_dir / "structural_work_validation.json",
        {"status": status, "rows": structural_rows},
    )
    write_json(
        args.out_dir / "analysis_manifest.json",
        {
            "schema_version": 1,
            "status": status,
            "contract_id": contract["contract_id"],
            "contract": str(contract_path),
            "contract_sha256": sha256_file(contract_path),
            "frozen_model": str(frozen_path),
            "frozen_model_sha256": sha256_file(frozen_path),
            "holdout_used_for_fit": False,
            "missing": missing,
            "calibration_total_summary": calibration_total,
            "calibration_component_summary": calibration_components,
            "holdout_total_summary": holdout_total,
            "holdout_component_summary": holdout_components,
            "evidence": evidence,
        },
    )
    print(f"SPINE_COMPONENT_FEATURES_V14_{status} missing={len(missing)}")
    return 0 if status == "PASS" or (status == "INCOMPLETE" and args.allow_partial) else 1


if __name__ == "__main__":
    raise SystemExit(main())
