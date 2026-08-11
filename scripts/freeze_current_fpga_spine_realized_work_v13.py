#!/usr/bin/env python3
"""Freeze the Spine v13 HLS-work timing model before PK/LJ08 holdout runs."""

from __future__ import annotations

import argparse
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
from spine_cycle_sim.calibration.current_fpga import (  # noqa: E402
    CurrentFPGAComponentRecord,
    SpineRealizedWorkRecord,
    fit_component_scale_calibration_only,
    fit_spine_realized_work_model,
    spine_realized_work_prediction_rows,
)


DEFAULT_CONTRACT = ROOT / "configs/contracts/current_fpga_spine_realized_work_v13.json"
DEFAULT_CASES = ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v7.json"
DEFAULT_CALIBRATION_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_20260812"
)
DEFAULT_HOLDOUT_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v13_20260812"
)
DEFAULT_HARDWARE_ROOT = Path(
    "/home/chuxiao/grasu-regraph-integration/docs/evidence/sharded_k4_fullgraph_20260806"
)
DEFAULT_WORKLOAD_ROOT = Path("/data/tmp/chuxiao/fullgraph_fpga_workloads_20260806")
DEFAULT_OUT = ROOT / "docs/evaluation_refresh_20260810/calibration_v13_frozen"


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


def median_hardware_cycles(records: list[dict[str, str]], field: str, clock_mhz: float) -> float:
    return statistics.median(float(record[field]) for record in records) * clock_mhz * 1000.0


def work_counters(algorithm: str, result: dict[str, Any]) -> tuple[int, float, float]:
    if algorithm == "weighted_sssp":
        return (
            int(result["rounds"]),
            float(sum(result["reader_range_tasks_per_round"])),
            float(sum(result["processed_edges_per_round"])),
        )
    if algorithm == "connected_components":
        return (
            int(result["iterations"]),
            float(sum(result["reader_range_tasks_per_iteration"])),
            float(sum(result["reader_edges_per_iteration"])),
        )
    raise ValueError(f"algorithm has no iterative realized-work model: {algorithm}")


def pin_holdout_workloads(
    workload_root: Path, datasets: list[str]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for dataset in datasets:
        for tag in ("weighted_sssp", "connected_components", "residual_pagerank"):
            metadata_path = workload_root / f"{dataset}_{tag}_insert_u8.json"
            metadata = read_json(metadata_path)
            graph = Path(metadata["pma_graph"])
            initial = Path(metadata["initial_slice"])
            update = Path(metadata["update_slice"])
            observed = {
                "pma_graph_sha256": sha256_file(graph),
                "initial_slice_sha256": sha256_file(initial),
                "update_slice_sha256": sha256_file(update),
            }
            for field, value in observed.items():
                if metadata.get(field) != value:
                    raise ValueError(f"holdout workload hash mismatch: {metadata_path}:{field}")
            rows.append(
                {
                    "dataset": dataset,
                    "workload_algorithm": tag,
                    "metadata": str(metadata_path.resolve()),
                    "metadata_sha256": sha256_file(metadata_path),
                    "pma_graph": str(graph.resolve()),
                    "initial_slice": str(initial.resolve()),
                    "update_slice": str(update.resolve()),
                    **observed,
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--calibration-root", type=Path, default=DEFAULT_CALIBRATION_ROOT)
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
    clock_mhz = float(contract["clock_mhz"])
    plugin_path = ROOT / contract["simulator_plugin"]["path"]
    if sha256_file(plugin_path) != contract["simulator_plugin"]["sha256"]:
        raise ValueError("immutable simulator plugin hash mismatch")

    for dataset in holdout_datasets:
        holdout_dataset_root = args.holdout_root.resolve() / "runs_current_v1" / dataset
        if holdout_dataset_root.exists() and any(holdout_dataset_root.rglob("result.json")):
            raise ValueError(f"holdout result existed before freeze: {dataset}")

    iterative_records: list[SpineRealizedWorkRecord] = []
    maintenance_records: dict[str, list[CurrentFPGAComponentRecord]] = {
        algorithm: [] for algorithm in cases["algorithms"]
    }
    evidence: list[dict[str, object]] = []
    for algorithm, algorithm_spec in cases["algorithms"].items():
        for dataset in calibration_datasets:
            run_dir = run_directory(
                args.calibration_root.resolve(), algorithm_spec, dataset, "spine"
            )
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
            profile_id = contract["profiles"][algorithm]
            maintenance_records[algorithm].append(
                CurrentFPGAComponentRecord(
                    "spine",
                    algorithm,
                    profile_id,
                    dataset,
                    "calibration",
                    "maintenance",
                    float(result["maintenance_cycles"]),
                    median_hardware_cycles(hardware, "maintenance_kernel_ms", clock_mhz),
                    "median routed maintenance kernel event",
                )
            )
            if algorithm in {"weighted_sssp", "connected_components"}:
                rounds, tasks, edges = work_counters(algorithm, result)
                iterative_records.append(
                    SpineRealizedWorkRecord(
                        algorithm,
                        profile_id,
                        dataset,
                        "calibration",
                        rounds,
                        tasks,
                        edges,
                        median_hardware_cycles(hardware, "reader_ms", clock_mhz),
                        median_hardware_cycles(hardware, "compute_ms", clock_mhz),
                        median_hardware_cycles(hardware, "kernel_span_ms", clock_mhz),
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

    iterative_model = fit_spine_realized_work_model(iterative_records)
    iterative_predictions = spine_realized_work_prediction_rows(
        iterative_records, iterative_model
    )
    maintenance_models = {
        algorithm: asdict(fit_component_scale_calibration_only(rows))
        for algorithm, rows in maintenance_records.items()
    }
    holdout_workloads = pin_holdout_workloads(
        args.workload_root.resolve(), holdout_datasets
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        args.out_dir / "frozen_spine_realized_work_model.json",
        {
            "schema_version": 1,
            "status": "FROZEN_BEFORE_HOLDOUT",
            "contract_id": contract["contract_id"],
            "iterative_model": asdict(iterative_model),
            "maintenance_models": maintenance_models,
            "fit_role": "calibration_only",
            "holdout_used_for_fit": False,
        },
    )
    write_json(
        args.out_dir / "calibration_predictions.json",
        {"schema_version": 1, "rows": iterative_predictions},
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
            "holdout_results_present": False,
            "calibration_evidence": evidence,
            "holdout_workloads": holdout_workloads,
        },
    )
    print(
        "SPINE_REALIZED_WORK_V13_FROZEN "
        f"calibration_rows={len(iterative_records)} holdout={','.join(holdout_datasets)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
