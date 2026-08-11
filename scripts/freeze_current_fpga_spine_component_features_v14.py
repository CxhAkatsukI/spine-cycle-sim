#!/usr/bin/env python3
"""Freeze the Spine v14 component-feature model before SO/LJ/LJ08 runs."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
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
    run_directory,
    unique_prefixed_record,
)
from scripts.freeze_current_fpga_spine_realized_work_v13 import (  # noqa: E402
    median_hardware_cycles,
    pin_holdout_workloads,
)
from spine_cycle_sim.calibration.current_fpga import (  # noqa: E402
    SpineComponentFeatureModel,
    SpineComponentFeatureRecord,
    fit_spine_component_feature_model,
    spine_component_feature_leave_one_dataset_out_rows,
    spine_component_feature_prediction_rows,
)


DEFAULT_CONTRACT = (
    ROOT / "configs/contracts/current_fpga_spine_component_features_v14.json"
)
DEFAULT_CASES = ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v7.json"
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
DEFAULT_WORKLOAD_ROOT = Path("/data/tmp/chuxiao/fullgraph_fpga_workloads_20260806")
DEFAULT_OUT = ROOT / "docs/evaluation_refresh_20260810/calibration_v14_frozen"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as sink:
        writer = csv.DictWriter(
            sink, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def sum_counter(result: dict[str, Any], field: str) -> float:
    value = result.get(field, 0)
    if isinstance(value, list):
        return float(sum(value))
    return float(value)


def component_active_cycles(result: dict[str, Any], component: str) -> float:
    active = sum_counter(result, f"{component}_active_cycles_per_round")
    if active:
        return active
    starts = result.get(f"{component}_start_cycles_per_round", [])
    ends = result.get(f"{component}_end_cycles_per_round", [])
    if len(starts) != len(ends):
        raise ValueError(f"unaligned {component} interval counters")
    return float(sum(int(end) - int(start) for start, end in zip(starts, ends)))


def component_request_count(result: dict[str, Any], component: str) -> float:
    per_round = sum_counter(result, f"{component}_memory_requests_issued_per_round")
    if per_round:
        completed = sum_counter(
            result, f"{component}_memory_requests_completed_per_round"
        )
        if per_round != completed:
            raise ValueError(f"{component} per-round request ledger is open")
        return per_round
    issued = float(result.get(f"{component}_component_parent_requests_issued", 0))
    completed = float(
        result.get(f"{component}_component_parent_requests_completed", 0)
    )
    if issued != completed:
        raise ValueError(f"{component} parent request ledger is open")
    return issued


def component_feature_record(
    *,
    algorithm: str,
    profile_id: str,
    dataset: str,
    role: str,
    result: dict[str, Any],
    hardware: list[dict[str, str]],
    clock_mhz: float,
) -> SpineComponentFeatureRecord:
    rounds = int(result.get("rounds", result.get("iterations", 0)))
    reader_cycles = component_active_cycles(result, "reader")
    compute_cycles = component_active_cycles(result, "compute")
    reader_requests = component_request_count(result, "reader")
    compute_requests = component_request_count(result, "compute")
    if rounds == 0 and any(
        value != 0
        for value in (
            reader_cycles,
            compute_cycles,
            reader_requests,
            compute_requests,
        )
    ):
        raise ValueError(f"zero-round row contains iterative work: {algorithm}:{dataset}")
    return SpineComponentFeatureRecord(
        algorithm=algorithm,
        profile_id=profile_id,
        dataset=dataset,
        role=role,
        rounds=rounds,
        simulator_maintenance_cycles=float(result["maintenance_cycles"]),
        simulator_reader_cycles=reader_cycles,
        simulator_compute_cycles=compute_cycles,
        simulator_reader_memory_requests=reader_requests,
        simulator_compute_memory_requests=compute_requests,
        hardware_maintenance_cycles=median_hardware_cycles(
            hardware, "maintenance_kernel_ms", clock_mhz
        ),
        hardware_reader_cycles=median_hardware_cycles(
            hardware, "reader_ms", clock_mhz
        ),
        hardware_compute_cycles=median_hardware_cycles(
            hardware, "compute_ms", clock_mhz
        ),
        hardware_iterative_span_cycles=median_hardware_cycles(
            hardware, "kernel_span_ms", clock_mhz
        ),
    )


def calibration_root(dataset: str, v12_root: Path, v13_root: Path) -> Path:
    return v13_root if dataset == "pk" else v12_root


def summarize_errors(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for algorithm in sorted({str(row["algorithm"]) for row in rows}):
        group = [row for row in rows if row["algorithm"] == algorithm]
        for component in (
            "maintenance",
            "reader",
            "compute",
            "iterative_span",
            "total",
        ):
            if component != "total" and component != "maintenance" and not any(
                int(row["rounds"]) for row in group
            ):
                continue
            errors = [
                float(row[f"{component}_absolute_error_percent"])
                for row in group
            ]
            summaries.append(
                {
                    "algorithm": algorithm,
                    "component": component,
                    "rows": len(group),
                    "median_absolute_error_percent": statistics.median(errors),
                    "max_absolute_error_percent": max(errors),
                }
            )
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--v12-root", type=Path, default=DEFAULT_V12_ROOT)
    parser.add_argument("--v13-root", type=Path, default=DEFAULT_V13_ROOT)
    parser.add_argument("--holdout-root", type=Path, default=DEFAULT_HOLDOUT_ROOT)
    parser.add_argument("--hardware-root", type=Path, default=DEFAULT_HARDWARE_ROOT)
    parser.add_argument("--workload-root", type=Path, default=DEFAULT_WORKLOAD_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    contract_path = args.contract.resolve()
    cases_path = args.cases.resolve()
    contract = read_json(contract_path)
    cases = read_json(cases_path)
    calibration_datasets = list(contract["roles"]["calibration"])
    holdout_datasets = list(contract["roles"]["holdout"])
    if set(calibration_datasets) & set(holdout_datasets):
        raise ValueError("calibration and holdout datasets overlap")
    plugin_path = ROOT / contract["simulator_plugin"]["path"]
    if sha256_file(plugin_path) != contract["simulator_plugin"]["sha256"]:
        raise ValueError("immutable simulator plugin hash mismatch")
    holdout_root = args.holdout_root.resolve()
    for dataset in holdout_datasets:
        dataset_root = holdout_root / "runs_current_v1" / dataset
        if dataset_root.exists() and any(dataset_root.rglob("result.json")):
            raise ValueError(f"holdout result existed before freeze: {dataset}")

    clock_mhz = float(contract["clock_mhz"])
    records_by_algorithm: dict[str, list[SpineComponentFeatureRecord]] = {}
    evidence: list[dict[str, object]] = []
    for algorithm, algorithm_spec in cases["algorithms"].items():
        records: list[SpineComponentFeatureRecord] = []
        for dataset in calibration_datasets:
            root = calibration_root(
                dataset, args.v12_root.resolve(), args.v13_root.resolve()
            )
            run_dir = run_directory(root, algorithm_spec, dataset, "spine")
            result, result_path, manifest_path = load_admitted_result(run_dir)
            manifest = read_json(manifest_path)
            if manifest.get("sst_plugin_sha256") != contract["simulator_plugin"]["sha256"]:
                raise ValueError(f"plugin mismatch: {algorithm}:{dataset}")
            logs = discover_hardware_logs(
                args.hardware_root.resolve(), algorithm_spec, dataset, "spine"
            )
            if len(logs) < 3:
                raise ValueError(f"three routed logs required: {algorithm}:{dataset}")
            hardware = [unique_prefixed_record(path, "SPINE_HW_TIMING") for path in logs]
            records.append(
                component_feature_record(
                    algorithm=algorithm,
                    profile_id=contract["profiles"][algorithm],
                    dataset=dataset,
                    role="calibration",
                    result=result,
                    hardware=hardware,
                    clock_mhz=clock_mhz,
                )
            )
            evidence.append(
                {
                    "algorithm": algorithm,
                    "dataset": dataset,
                    "simulator_result": str(result_path.resolve()),
                    "simulator_result_sha256": sha256_file(result_path),
                    "simulator_manifest": str(manifest_path.resolve()),
                    "simulator_manifest_sha256": sha256_file(manifest_path),
                    "hardware_logs": [str(path) for path in logs],
                    "hardware_log_sha256": [sha256_file(path) for path in logs],
                }
            )
        records_by_algorithm[algorithm] = records

    models: dict[str, SpineComponentFeatureModel] = {}
    calibration_predictions: list[dict[str, object]] = []
    leave_one_out: list[dict[str, object]] = []
    for algorithm, records in records_by_algorithm.items():
        models[algorithm] = fit_spine_component_feature_model(records)
        calibration_predictions.extend(
            spine_component_feature_prediction_rows(records, models[algorithm])
        )
        leave_one_out.extend(
            spine_component_feature_leave_one_dataset_out_rows(records)
        )

    holdout_workloads = pin_holdout_workloads(
        args.workload_root.resolve(), holdout_datasets
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        args.out_dir / "frozen_spine_component_feature_models.json",
        {
            "schema_version": 1,
            "status": "FROZEN_BEFORE_HOLDOUT",
            "contract_id": contract["contract_id"],
            "fit_role": "calibration_only",
            "holdout_used_for_fit": False,
            "models": {
                algorithm: asdict(model) for algorithm, model in models.items()
            },
        },
    )
    write_csv(args.out_dir / "calibration_predictions.csv", calibration_predictions)
    write_csv(args.out_dir / "leave_one_dataset_out.csv", leave_one_out)
    write_json(
        args.out_dir / "development_summary.json",
        {
            "schema_version": 1,
            "calibration_fit": summarize_errors(calibration_predictions),
            "leave_one_dataset_out": summarize_errors(leave_one_out),
            "note": "Leave-one-dataset-out rows are development evidence, not the independent holdout.",
        },
    )
    write_json(
        args.out_dir / "freeze_manifest.json",
        {
            "schema_version": 1,
            "status": "FROZEN_BEFORE_HOLDOUT",
            "contract": str(contract_path),
            "contract_sha256": sha256_file(contract_path),
            "cases": str(cases_path),
            "cases_sha256": sha256_file(cases_path),
            "plugin": str(plugin_path.resolve()),
            "plugin_sha256": sha256_file(plugin_path),
            "calibration_datasets": calibration_datasets,
            "holdout_datasets": holdout_datasets,
            "holdout_root": str(holdout_root),
            "holdout_results_present": False,
            "calibration_evidence": evidence,
            "holdout_workloads": holdout_workloads,
        },
    )
    print(
        "SPINE_COMPONENT_FEATURES_V14_FROZEN "
        f"calibration_rows={sum(map(len, records_by_algorithm.values()))} "
        f"holdout={','.join(holdout_datasets)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
