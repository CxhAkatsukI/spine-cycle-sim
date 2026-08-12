#!/usr/bin/env python3
"""Freeze the Spine v15 HLS-mechanism model before LJ/LJ08 runs."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_current_fpga_components import (  # noqa: E402
    discover_hardware_logs,
    load_admitted_result,
    run_directory,
    unique_prefixed_record,
)
from scripts.freeze_current_fpga_spine_component_features_v14 import (  # noqa: E402
    DEFAULT_CASES,
    DEFAULT_HARDWARE_ROOT,
    DEFAULT_V12_ROOT,
    DEFAULT_V13_ROOT,
    DEFAULT_WORKLOAD_ROOT,
    component_feature_record,
    read_json,
    sha256_file,
    summarize_errors,
    write_csv,
    write_json,
)
from scripts.freeze_current_fpga_spine_realized_work_v13 import (  # noqa: E402
    pin_holdout_workloads,
)
from spine_cycle_sim.calibration.current_fpga import (  # noqa: E402
    SpineMechanismComponentModel,
    SpineMechanismComponentRecord,
    fit_spine_mechanism_component_model,
    spine_mechanism_component_leave_one_dataset_out_rows,
    spine_mechanism_component_prediction_rows,
)


DEFAULT_CONTRACT = (
    ROOT / "configs/contracts/current_fpga_spine_mechanism_components_v15.json"
)
DEFAULT_V14_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v14_20260812"
)
DEFAULT_OUT = ROOT / "docs/evaluation_refresh_20260810/calibration_v15_frozen"


def calibration_root(
    dataset: str, v12_root: Path, v13_root: Path, v14_root: Path
) -> Path:
    if dataset == "pk":
        return v13_root
    if dataset == "so":
        return v14_root
    return v12_root


def mechanism_record(
    *,
    algorithm: str,
    profile_id: str,
    dataset: str,
    role: str,
    result: dict,
    hardware: list[dict[str, str]],
    clock_mhz: float,
) -> SpineMechanismComponentRecord:
    feature = component_feature_record(
        algorithm=algorithm,
        profile_id=profile_id,
        dataset=dataset,
        role=role,
        result=result,
        hardware=hardware,
        clock_mhz=clock_mhz,
    )
    return SpineMechanismComponentRecord(
        algorithm=feature.algorithm,
        profile_id=feature.profile_id,
        dataset=feature.dataset,
        role=feature.role,
        rounds=feature.rounds,
        vertices=float(result["vertices"]),
        simulator_maintenance_cycles=feature.simulator_maintenance_cycles,
        simulator_reader_cycles=feature.simulator_reader_cycles,
        simulator_compute_cycles=feature.simulator_compute_cycles,
        simulator_reader_memory_requests=(
            feature.simulator_reader_memory_requests
        ),
        simulator_compute_memory_requests=(
            feature.simulator_compute_memory_requests
        ),
        hardware_maintenance_cycles=feature.hardware_maintenance_cycles,
        hardware_reader_cycles=feature.hardware_reader_cycles,
        hardware_compute_cycles=feature.hardware_compute_cycles,
        hardware_iterative_span_cycles=feature.hardware_iterative_span_cycles,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--v12-root", type=Path, default=DEFAULT_V12_ROOT)
    parser.add_argument("--v13-root", type=Path, default=DEFAULT_V13_ROOT)
    parser.add_argument("--v14-root", type=Path, default=DEFAULT_V14_ROOT)
    parser.add_argument("--holdout-root", type=Path, default=DEFAULT_V14_ROOT)
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
    records_by_algorithm: dict[str, list[SpineMechanismComponentRecord]] = {}
    evidence: list[dict[str, object]] = []
    for algorithm, algorithm_spec in cases["algorithms"].items():
        records: list[SpineMechanismComponentRecord] = []
        for dataset in calibration_datasets:
            root = calibration_root(
                dataset,
                args.v12_root.resolve(),
                args.v13_root.resolve(),
                args.v14_root.resolve(),
            )
            run_dir = run_directory(root, algorithm_spec, dataset, "spine")
            result, result_path, manifest_path = load_admitted_result(run_dir)
            manifest = read_json(manifest_path)
            if (
                manifest.get("sst_plugin_sha256")
                != contract["simulator_plugin"]["sha256"]
            ):
                raise ValueError(f"plugin mismatch: {algorithm}:{dataset}")
            logs = discover_hardware_logs(
                args.hardware_root.resolve(), algorithm_spec, dataset, "spine"
            )
            if len(logs) < 3:
                raise ValueError(
                    f"three routed logs required: {algorithm}:{dataset}"
                )
            hardware = [
                unique_prefixed_record(path, "SPINE_HW_TIMING") for path in logs
            ]
            records.append(
                mechanism_record(
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

    models: dict[str, SpineMechanismComponentModel] = {}
    calibration_predictions: list[dict[str, object]] = []
    leave_one_out: list[dict[str, object]] = []
    for algorithm, records in records_by_algorithm.items():
        compute_strategy = contract["compute_strategies"][algorithm]
        models[algorithm] = fit_spine_mechanism_component_model(
            records, compute_strategy=compute_strategy
        )
        calibration_predictions.extend(
            spine_mechanism_component_prediction_rows(
                records, models[algorithm]
            )
        )
        leave_one_out.extend(
            spine_mechanism_component_leave_one_dataset_out_rows(
                records, compute_strategy=compute_strategy
            )
        )

    holdout_workloads = pin_holdout_workloads(
        args.workload_root.resolve(), holdout_datasets
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        args.out_dir / "frozen_spine_mechanism_component_models.json",
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
            "note": (
                "Leave-one-dataset-out rows are development evidence, not "
                "frozen transfer validation."
            ),
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
        "SPINE_MECHANISM_COMPONENTS_V15_FROZEN "
        f"calibration_rows={sum(map(len, records_by_algorithm.values()))} "
        f"holdout={','.join(holdout_datasets)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
