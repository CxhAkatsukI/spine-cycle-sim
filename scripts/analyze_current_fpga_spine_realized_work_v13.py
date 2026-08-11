#!/usr/bin/env python3
"""Apply the frozen Spine v13 realized-work model to independent holdouts."""

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
from scripts.freeze_current_fpga_spine_realized_work_v13 import (  # noqa: E402
    median_hardware_cycles,
    work_counters,
)
from spine_cycle_sim.calibration.current_fpga import (  # noqa: E402
    PositiveScaleModel,
    SpineRealizedWorkModel,
    SpineRealizedWorkRecord,
    absolute_error_percent,
    spearman_rank_correlation,
    spine_realized_work_prediction_rows,
)


DEFAULT_CONTRACT = ROOT / "configs/contracts/current_fpga_spine_realized_work_v13.json"
DEFAULT_CASES = ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v7.json"
DEFAULT_FROZEN = (
    ROOT
    / "docs/evaluation_refresh_20260810/calibration_v13_frozen"
    / "frozen_spine_realized_work_model.json"
)
DEFAULT_CALIBRATION_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_20260812"
)
DEFAULT_HOLDOUT_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v13_20260812"
)
DEFAULT_HARDWARE_ROOT = Path(
    "/home/chuxiao/grasu-regraph-integration/docs/evidence/sharded_k4_fullgraph_20260806"
)
DEFAULT_OUT = ROOT / "docs/evaluation_refresh_20260810/calibration_v13_holdout"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def dataclass_from_dict(cls: type, payload: dict[str, Any]):
    names = {field.name for field in fields(cls)}
    return cls(**{name: payload[name] for name in names})


def result_root_for_role(
    role: str, calibration_root: Path, holdout_root: Path
) -> Path:
    return calibration_root if role == "calibration" else holdout_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--frozen-model", type=Path, default=DEFAULT_FROZEN)
    parser.add_argument("--calibration-root", type=Path, default=DEFAULT_CALIBRATION_ROOT)
    parser.add_argument("--holdout-root", type=Path, default=DEFAULT_HOLDOUT_ROOT)
    parser.add_argument("--hardware-root", type=Path, default=DEFAULT_HARDWARE_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    contract = read_json(args.contract.resolve())
    cases = read_json(args.cases.resolve())
    frozen = read_json(args.frozen_model.resolve())
    if frozen.get("status") != "FROZEN_BEFORE_HOLDOUT":
        raise ValueError("model is not a pre-holdout freeze")
    if frozen.get("contract_id") != contract["contract_id"]:
        raise ValueError("frozen model and contract differ")
    if frozen.get("holdout_used_for_fit") is not False:
        raise ValueError("frozen model used holdout data")

    iterative_model = dataclass_from_dict(
        SpineRealizedWorkModel, frozen["iterative_model"]
    )
    maintenance_models = {
        algorithm: dataclass_from_dict(PositiveScaleModel, payload)
        for algorithm, payload in frozen["maintenance_models"].items()
    }
    roles = {
        dataset: role
        for role in ("calibration", "holdout")
        for dataset in contract["roles"][role]
    }
    clock_mhz = float(contract["clock_mhz"])
    iterative_records: list[SpineRealizedWorkRecord] = []
    total_rows: list[dict[str, object]] = []
    ledger_rows: list[dict[str, object]] = []
    structural_rows: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    missing: list[str] = []

    profile_paths = {
        entry["profile_id"]: ROOT / entry["path"]
        for entry in read_json(
            ROOT / "configs/contracts/evaluation_refresh_fpga_calibration_v8.json"
        )["architecture_profiles"]
        if entry["architecture"] == "spine"
    }
    for algorithm, algorithm_spec in cases["algorithms"].items():
        for dataset, role in roles.items():
            root = result_root_for_role(
                role, args.calibration_root.resolve(), args.holdout_root.resolve()
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
            profile_id = contract["profiles"][algorithm]
            maintenance_prediction = maintenance_models[algorithm].predict(
                float(result["maintenance_cycles"])
            )
            hardware_maintenance = median_hardware_cycles(
                hardware, "maintenance_kernel_ms", clock_mhz
            )
            hardware_iterations = int(
                statistics.median(int(record["iterations"]) for record in hardware)
            )
            predicted_span = 0.0
            hardware_span = median_hardware_cycles(hardware, "kernel_span_ms", clock_mhz)
            if algorithm in {"weighted_sssp", "connected_components"}:
                rounds, tasks, edges = work_counters(algorithm, result)
                iterative_records.append(
                    SpineRealizedWorkRecord(
                        algorithm,
                        profile_id,
                        dataset,
                        role,
                        rounds,
                        tasks,
                        edges,
                        median_hardware_cycles(hardware, "reader_ms", clock_mhz),
                        median_hardware_cycles(hardware, "compute_ms", clock_mhz),
                        hardware_span,
                    )
                )
                predicted_span = iterative_model.predict_components(
                    rounds=rounds, range_tasks=tasks, processed_edges=edges
                )["iterative_span_cycles"]
            elif int(result.get("iterations", 0)) != 0 or hardware_iterations != 0:
                raise ValueError(
                    f"residual PageRank has nonzero propagation outside frozen model: {dataset}"
                )
            predicted_total = maintenance_prediction + predicted_span
            hardware_total = hardware_maintenance + hardware_span
            total_rows.append(
                {
                    "algorithm": algorithm,
                    "dataset": dataset,
                    "role": role,
                    "profile_id": profile_id,
                    "simulator_maintenance_cycles": result["maintenance_cycles"],
                    "hardware_maintenance_cycles": hardware_maintenance,
                    "predicted_maintenance_cycles": maintenance_prediction,
                    "hardware_iterative_span_cycles": hardware_span,
                    "predicted_iterative_span_cycles": predicted_span,
                    "hardware_total_cycles": hardware_total,
                    "predicted_total_cycles": predicted_total,
                    "total_absolute_error_percent": absolute_error_percent(
                        predicted_total, hardware_total
                    ),
                }
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
            structural["profile_id"] = profile_id
            structural_rows.append(structural)
            profile = read_json(profile_paths[profile_id])["parameters"]
            ledger = memory_ledger_row(
                "spine", algorithm, dataset, role, result, result_path, profile
            )
            ledger["profile_id"] = profile_id
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

    component_rows = spine_realized_work_prediction_rows(
        iterative_records, iterative_model
    )
    holdout_totals = [row for row in total_rows if row["role"] == "holdout"]
    total_summary: list[dict[str, object]] = []
    for algorithm in cases["algorithms"]:
        rows = [row for row in holdout_totals if row["algorithm"] == algorithm]
        if not rows:
            continue
        errors = [float(row["total_absolute_error_percent"]) for row in rows]
        rank = (
            spearman_rank_correlation(
                [float(row["predicted_total_cycles"]) for row in rows],
                [float(row["hardware_total_cycles"]) for row in rows],
            )
            if len(rows) >= 2
            else 0.0
        )
        total_summary.append(
            {
                "algorithm": algorithm,
                "holdout_cases": len(rows),
                "median_absolute_error_percent": statistics.median(errors),
                "max_absolute_error_percent": max(errors),
                "workload_rank_spearman": rank,
            }
        )
    component_summary: list[dict[str, object]] = []
    for component in ("reader", "compute", "iterative_span"):
        rows = [row for row in component_rows if row["role"] == "holdout"]
        if not rows:
            continue
        errors = [float(row[f"{component}_absolute_error_percent"]) for row in rows]
        component_summary.append(
            {
                "component": component,
                "holdout_cases": len(rows),
                "median_absolute_error_percent": statistics.median(errors),
                "max_absolute_error_percent": max(errors),
            }
        )

    thresholds = contract["thresholds"]
    status = "INCOMPLETE" if missing else "PASS"
    if not missing:
        if any(row["status"] != "PASS" for row in ledger_rows + structural_rows):
            status = "FAIL"
        if any(
            float(row["median_absolute_error_percent"])
            > thresholds["holdout_total_median_absolute_error_percent_max"]
            or float(row["max_absolute_error_percent"])
            > thresholds["holdout_total_absolute_error_percent_max"]
            or float(row["workload_rank_spearman"])
            < thresholds["workload_rank_spearman_min"]
            for row in total_summary
        ):
            status = "FAIL"
        if any(
            float(row["median_absolute_error_percent"])
            > thresholds["holdout_component_median_absolute_error_percent_max"]
            for row in component_summary
        ):
            status = "FAIL"

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "total_rows.csv", total_rows)
    write_csv(args.out_dir / "total_summary.csv", total_summary)
    write_csv(args.out_dir / "component_rows.csv", component_rows)
    write_csv(args.out_dir / "component_summary.csv", component_summary)
    write_json(args.out_dir / "memory_ledger_validation.json", {"status": status, "rows": ledger_rows})
    write_json(args.out_dir / "structural_work_validation.json", {"status": status, "rows": structural_rows})
    write_json(
        args.out_dir / "analysis_manifest.json",
        {
            "schema_version": 1,
            "status": status,
            "contract_id": contract["contract_id"],
            "frozen_model": str(args.frozen_model.resolve()),
            "frozen_model_sha256": sha256_file(args.frozen_model.resolve()),
            "holdout_used_for_fit": False,
            "missing": missing,
            "total_summary": total_summary,
            "component_summary": component_summary,
            "evidence": evidence,
        },
    )
    print(f"SPINE_REALIZED_WORK_V13_{status} missing={len(missing)}")
    return 0 if status == "PASS" or (status == "INCOMPLETE" and args.allow_partial) else 1


if __name__ == "__main__":
    raise SystemExit(main())
