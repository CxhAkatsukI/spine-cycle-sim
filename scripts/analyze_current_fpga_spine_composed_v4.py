#!/usr/bin/env python3
"""Fit and validate the frozen current-FPGA Spine composed timing model."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import csv
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
    memory_ledger_row,
    prefixed_records,
    spine_structural_work_row,
    unique_prefixed_record,
)
from spine_cycle_sim.calibration.current_fpga import (  # noqa: E402
    CurrentFPGAComposedRecord,
    composed_prediction_rows,
    fit_composed_timing_model,
    spearman_rank_correlation,
)


DEFAULT_CONTRACT = ROOT / "configs/contracts/current_fpga_spine_composed_cases_v4.json"
DEFAULT_INDEX = ROOT / "docs/evidence/current_fpga_spine_composed_index_v4.json"
DEFAULT_OUT = ROOT / "docs/evaluation_refresh_20260810/calibration_v4"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def role_for(contract: dict[str, Any], algorithm: str, dataset: str) -> str:
    spec = contract["algorithms"][algorithm]
    if algorithm != "thresholded_residual_pagerank":
        for role in ("calibration", "development_validation", "holdout"):
            if dataset in spec[role]:
                return role
        raise ValueError(f"unfrozen dataset {algorithm}:{dataset}")
    if dataset in spec["iterative_calibration"]:
        return "calibration"
    if dataset in spec["iterative_holdout"]:
        return "holdout"
    if dataset in spec["maintenance_calibration"]:
        return "calibration"
    if dataset in spec["development_validation"]:
        return "development_validation"
    if dataset in spec["maintenance_holdout"]:
        return "holdout"
    raise ValueError(f"unfrozen dataset {algorithm}:{dataset}")


def expected_pairs(contract: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for algorithm, spec in contract["algorithms"].items():
        fields = (
            ("calibration", "development_validation", "holdout")
            if algorithm != "thresholded_residual_pagerank"
            else (
                "maintenance_calibration",
                "development_validation",
                "maintenance_holdout",
            )
        )
        for field in fields:
            pairs.update((algorithm, dataset) for dataset in spec[field])
    return pairs


def load_admitted_result(
    run_dir: Path, contract: dict[str, Any], profile_spec: dict[str, Any]
) -> tuple[dict[str, Any], Path, Path]:
    result_path = run_dir / "result.json"
    manifest_path = next(
        (
            run_dir / name
            for name in ("run_manifest.json", "manifest.json", "summary.json")
            if (run_dir / name).is_file()
        ),
        run_dir / "run_manifest.json",
    )
    if not result_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(run_dir)
    result = read_json(result_path)
    manifest = read_json(manifest_path)
    if result.get("success") is not True or manifest.get("status") != "PASS":
        raise ValueError(f"simulator admission failed: {run_dir}")
    for key in (
        "correctness_mismatches",
        "architecture_correctness_mismatches",
        "mathematical_correctness_mismatches",
    ):
        if int(result.get(key, 0)) != 0:
            raise ValueError(f"nonzero {key}: {run_dir}")
    observed_profile = result.get(
        "architecture_profile_id", manifest.get("profile_id")
    )
    if observed_profile != profile_spec["profile_id"]:
        raise ValueError(f"profile mismatch: {run_dir}")
    observed_profile_sha = manifest.get(
        "profile_sha256", result.get("architecture_profile_sha256")
    )
    if observed_profile_sha != profile_spec["profile_sha256"]:
        raise ValueError(f"profile hash mismatch: {run_dir}")
    plugin = manifest.get("sst_plugin_sha256")
    current = contract["simulator_plugin"]["sha256"]
    legacy = contract["legacy_plugin_reuse"]["sha256"]
    if plugin == legacy:
        if int(result.get("resident_hot_vertices", 0)) != 0:
            raise ValueError(f"affected legacy Spine row requires v4 successor: {run_dir}")
    elif plugin != current:
        raise ValueError(f"unfrozen plugin identity: {run_dir}")
    return result, result_path, manifest_path


def median_field(records: list[dict[str, str]], field: str) -> float:
    values = [float(record[field]) for record in records]
    if not values or min(values) < 0:
        raise ValueError(f"invalid hardware field {field}")
    return statistics.median(values)


def iterations_and_work(
    algorithm: str, result: dict[str, Any]
) -> tuple[int, list[int], list[int]]:
    if algorithm == "weighted_sssp":
        return (
            int(result["rounds"]),
            [int(value) for value in result["reader_range_tasks_per_round"]],
            [int(value) for value in result["processed_edges_per_round"]],
        )
    if algorithm == "connected_components":
        return (
            int(result["iterations"]),
            [int(value) for value in result["reader_range_tasks_per_iteration"]],
            [int(value) for value in result["reader_edges_per_iteration"]],
        )
    return (
        int(result["iterations"]),
        [int(value) for value in result.get("reader_range_tasks_per_iteration", [])],
        [int(value) for value in result.get("reader_edges_per_iteration", [])],
    )


def summarize_predictions(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for role in ("calibration", "development_validation", "holdout"):
        selected = [row for row in rows if row["role"] == role]
        if not selected:
            continue
        predicted = [float(row["predicted_total_cycles"]) for row in selected]
        observed = [float(row["hardware_total_cycles"]) for row in selected]
        summaries.append(
            {
                "architecture": "spine",
                "algorithm": selected[0]["algorithm"],
                "role": role,
                "cases": len(selected),
                "median_absolute_error_percent": statistics.median(
                    float(row["total_absolute_error_percent"]) for row in selected
                ),
                "max_absolute_error_percent": max(
                    float(row["total_absolute_error_percent"]) for row in selected
                ),
                "rank_spearman": (
                    spearman_rank_correlation(predicted, observed)
                    if len(selected) >= 2
                    else None
                ),
            }
        )
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--evidence-index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    contract_path = args.contract.resolve()
    index_path = args.evidence_index.resolve()
    contract = read_json(contract_path)
    index = read_json(index_path)
    if contract.get("status") != "frozen_before_holdout_execution":
        raise ValueError("v4 contract was not frozen before holdout execution")
    if index.get("contract_id") != contract.get("contract_id"):
        raise ValueError("evidence index and contract disagree")
    plugin_path = ROOT / contract["simulator_plugin"]["path"]
    if (
        not plugin_path.is_file()
        or sha256_file(plugin_path) != contract["simulator_plugin"]["sha256"]
    ):
        raise ValueError("frozen v4 simulator plugin identity mismatch")
    for spec in contract["algorithms"].values():
        profile_path = ROOT / spec["profile_path"]
        if not profile_path.is_file() or sha256_file(profile_path) != spec["profile_sha256"]:
            raise ValueError(f"frozen profile identity mismatch: {profile_path}")
    indexed = {(row["algorithm"], row["dataset"]): row for row in index["rows"]}
    if len(indexed) != len(index["rows"]):
        raise ValueError("duplicate evidence-index row")
    expected = expected_pairs(contract)
    extra = set(indexed) - expected
    if extra:
        raise ValueError(f"unfrozen evidence rows: {sorted(extra)}")
    missing = sorted(expected - set(indexed))
    if missing and not args.allow_partial:
        raise ValueError(f"missing frozen evidence rows: {missing}")

    clock_mhz = float(contract["clock_mhz"])
    grouped: dict[str, list[CurrentFPGAComposedRecord]] = {
        algorithm: [] for algorithm in contract["algorithms"]
    }
    evidence_rows: list[dict[str, object]] = []
    structural_rows: list[dict[str, object]] = []
    ledger_rows: list[dict[str, object]] = []
    for algorithm, dataset in sorted(set(indexed) & expected):
        spec = contract["algorithms"][algorithm]
        role = role_for(contract, algorithm, dataset)
        entry = indexed[(algorithm, dataset)]
        run_dir = Path(entry["run_dir"]).resolve()
        result, result_path, manifest_path = load_admitted_result(
            run_dir, contract, spec
        )
        hardware_logs = [Path(path).resolve() for path in entry["hardware_logs"]]
        if len(hardware_logs) != 3 or any(not path.is_file() for path in hardware_logs):
            raise ValueError(f"three hardware logs required for {algorithm}:{dataset}")
        timing = [unique_prefixed_record(path, "SPINE_HW_TIMING") for path in hardware_logs]
        iterations, simulator_tasks, simulator_edges = iterations_and_work(
            algorithm, result
        )
        simulator_maintenance = float(result["maintenance_cycles"])
        simulator_iterative = (
            0.0 if iterations == 0 else float(result["cycles"]) - simulator_maintenance
        )
        hardware_maintenance = median_field(timing, "maintenance_kernel_ms") * clock_mhz * 1000.0
        hardware_iterative = median_field(timing, "kernel_span_ms") * clock_mhz * 1000.0
        record = CurrentFPGAComposedRecord(
            "spine",
            algorithm,
            spec["profile_id"],
            dataset,
            role,
            simulator_maintenance,
            simulator_iterative,
            iterations,
            hardware_maintenance,
            hardware_iterative,
        )
        grouped[algorithm].append(record)

        structural = spine_structural_work_row(
            algorithm, dataset, role, result, result_path, hardware_logs, timing
        )
        structural_rows.append(structural)
        ledger_rows.append(
            memory_ledger_row("spine", algorithm, dataset, role, result, result_path)
        )
        evidence_rows.append(
            {
                "algorithm": algorithm,
                "dataset": dataset,
                "role": role,
                "run_dir": str(run_dir),
                "result_sha256": sha256_file(result_path),
                "manifest_sha256": sha256_file(manifest_path),
                "plugin_sha256": read_json(manifest_path)["sst_plugin_sha256"],
                "hardware_logs": [str(path) for path in hardware_logs],
                "hardware_log_sha256": [sha256_file(path) for path in hardware_logs],
                "simulator_tasks": simulator_tasks,
                "simulator_edges": simulator_edges,
            }
        )

    predictions: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    models: list[dict[str, object]] = []
    for algorithm, records in grouped.items():
        if not records:
            continue
        strategy = contract["algorithms"][algorithm]["iterative_strategy"]
        try:
            model = fit_composed_timing_model(records, iterative_strategy=strategy)
        except ValueError:
            if args.allow_partial:
                continue
            raise
        algorithm_rows = composed_prediction_rows(records, model)
        predictions.extend(algorithm_rows)
        summaries.extend(summarize_predictions(algorithm_rows))
        models.append({**asdict(model), "fit_role": "calibration_only"})

    thresholds = contract["thresholds"]
    validation_checks: list[dict[str, object]] = []
    for row in summaries:
        role = str(row["role"])
        if role == "calibration":
            continue
        median_limit = float(
            thresholds[
                "development_median_absolute_error_percent_max"
                if role == "development_validation"
                else "holdout_median_absolute_error_percent_max"
            ]
        )
        max_limit = float(thresholds["holdout_absolute_error_percent_max"])
        rank = row["rank_spearman"]
        validation_checks.append(
            {
                **row,
                "median_pass": float(row["median_absolute_error_percent"]) <= median_limit,
                "max_pass": float(row["max_absolute_error_percent"]) <= max_limit,
                "rank_pass": rank is None or float(rank) >= float(thresholds["rank_spearman_min"]),
            }
        )
    complete = not missing and len(models) == len(contract["algorithms"])
    passed = (
        complete
        and all(row["status"] == "PASS" for row in structural_rows)
        and all(row["status"] == "PASS" for row in ledger_rows)
        and all(
            row["median_pass"] and row["max_pass"] and row["rank_pass"]
            for row in validation_checks
        )
    )
    status = "PASS" if passed else ("INCOMPLETE" if not complete else "FAIL")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "spine_composed_rows.csv", predictions)
    write_csv(args.out_dir / "spine_composed_group_summary.csv", summaries)
    write_json(args.out_dir / "spine_composed_models.json", {"status": status, "models": models})
    write_json(
        args.out_dir / "spine_structural_work_validation.json",
        {"status": "PASS" if structural_rows and all(row["status"] == "PASS" for row in structural_rows) else "FAIL", "rows": structural_rows},
    )
    write_json(
        args.out_dir / "spine_memory_ledger_validation.json",
        {"status": "PASS" if ledger_rows and all(row["status"] == "PASS" for row in ledger_rows) else "FAIL", "rows": ledger_rows},
    )
    write_json(
        args.out_dir / "spine_composed_calibration.json",
        {
            "schema_version": 1,
            "status": status,
            "parameters_frozen": passed,
            "contract_id": contract["contract_id"],
            "contract_sha256": sha256_file(contract_path),
            "evidence_index_sha256": sha256_file(index_path),
            "calibration_and_holdout_disjoint": True,
            "hardware_reader_compute_intervals_summed": False,
            "zero_iteration_tail_excluded": True,
            "missing": [list(pair) for pair in missing],
            "validation_checks": validation_checks,
            "evidence": evidence_rows,
        },
    )
    print(
        f"CURRENT_FPGA_SPINE_COMPOSED_{status} rows={len(evidence_rows)} "
        f"models={len(models)} missing={len(missing)}"
    )
    return 0 if passed or (args.allow_partial and status == "INCOMPLETE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
