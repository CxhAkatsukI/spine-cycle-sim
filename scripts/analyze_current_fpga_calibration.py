#!/usr/bin/env python3
"""Fit current simulator totals to routed FPGA evidence with frozen holdouts."""

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

from spine_cycle_sim.calibration.current_fpga import (  # noqa: E402
    CurrentFPGATimingRecord,
    fit_total_scale,
    spearman_rank_correlation,
    total_prediction_rows,
)
from spine_cycle_sim.calibration.frozen import load_frozen_scale_models  # noqa: E402


DEFAULT_CASES = ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v5.json"
DEFAULT_CONTRACT = ROOT / "configs/contracts/evaluation_refresh_fpga_calibration_v6.json"
DEFAULT_OUT = ROOT / "docs/evaluation_refresh_20260810/calibration_v10_analysis"
ARCHITECTURES = ("spine", "grasu_regraph")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source, delimiter="\t"))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_simulator_result(run_dir: Path) -> tuple[dict[str, Any], Path, Path | None]:
    result_path = run_dir / "result.json"
    if not result_path.is_file():
        raise FileNotFoundError(result_path)
    result = read_json(result_path)
    manifest_path = next(
        (
            path
            for path in (
                run_dir / "run_manifest.json",
                run_dir / "summary.json",
                run_dir / "manifest.json",
            )
            if path.is_file()
        ),
        None,
    )
    if manifest_path is None:
        raise FileNotFoundError(run_dir / "run_manifest.json")
    manifest = read_json(manifest_path) if manifest_path else {}
    admitted = manifest.get("admitted", True)
    status = manifest.get("status", result.get("status"))
    if status != "PASS" or admitted is not True or result.get("success") is not True:
        raise ValueError(f"simulator correctness gate failed: {run_dir}")
    for field in (
        "correctness_mismatches",
        "architecture_correctness_mismatches",
        "mathematical_correctness_mismatches",
    ):
        if field in result and int(result[field]) != 0:
            raise ValueError(f"nonzero {field}: {run_dir}")
    cycles = float(result.get("cycles", 0))
    if cycles <= 0:
        raise ValueError(f"missing positive cycles: {run_dir}")
    return result, result_path, manifest_path


def profile_id_of(result: dict[str, Any], manifest: dict[str, Any]) -> str:
    for source in (result, manifest):
        for field in ("architecture_profile_id", "profile_id"):
            value = source.get(field)
            if isinstance(value, str) and value:
                return value
    profile = manifest.get("profile")
    if isinstance(profile, str) and profile:
        return Path(profile).stem
    raise ValueError("simulator evidence does not identify its architecture profile")


def profile_sha256_of(result: dict[str, Any], manifest: dict[str, Any]) -> str:
    for source in (manifest, result):
        for field in ("profile_sha256", "architecture_profile_sha256"):
            value = source.get(field)
            if isinstance(value, str) and value:
                return value
    raise ValueError("simulator evidence does not identify its architecture profile hash")


def validate_workload_identity(
    simulation_root: Path,
    dataset: str,
    algorithm: str,
    hardware_graph: str,
) -> dict[str, str]:
    metadata_path = simulation_root / "workloads" / f"{dataset}_{algorithm}_insert_u8.json"
    metadata = read_json(metadata_path)
    source_graph = Path(metadata["source_graph"]).resolve()
    expected_graph = Path(hardware_graph).resolve()
    if source_graph != expected_graph:
        raise ValueError(f"hardware/simulator graph mismatch: {metadata_path}")
    if not source_graph.is_file():
        raise FileNotFoundError(source_graph)
    actual_sha = sha256_file(source_graph)
    if metadata.get("source_graph_sha256") != actual_sha:
        raise ValueError(f"source graph hash mismatch: {metadata_path}")
    for field in ("initial_slice", "update_slice"):
        path = Path(metadata[field])
        if not path.is_file() or metadata.get(f"{field}_sha256") != sha256_file(path):
            raise ValueError(f"converted workload hash mismatch: {metadata_path}:{field}")
    return {
        "metadata": str(metadata_path.resolve()),
        "metadata_sha256": sha256_file(metadata_path),
        "source_graph": str(source_graph),
        "source_graph_sha256": actual_sha,
    }


def median(values: list[float]) -> float:
    return statistics.median(values)


def summarize_group(rows: list[dict[str, object]]) -> dict[str, object]:
    holdout = [row for row in rows if row["role"] == "holdout"]
    calibration = [row for row in rows if row["role"] == "calibration"]
    if len(calibration) < 2 or len(holdout) < 2:
        raise ValueError("group does not have two calibration and two holdout rows")
    rank = spearman_rank_correlation(
        [float(row["predicted_cycles"]) for row in rows],
        [float(row["hardware_cycles"]) for row in rows],
    )
    return {
        "architecture": rows[0]["architecture"],
        "algorithm": rows[0]["algorithm"],
        "profile_id": rows[0]["profile_id"],
        "calibration_cases": len(calibration),
        "holdout_cases": len(holdout),
        "calibration_median_absolute_error_percent": median(
            [float(row["absolute_error_percent"]) for row in calibration]
        ),
        "holdout_median_absolute_error_percent": median(
            [float(row["absolute_error_percent"]) for row in holdout]
        ),
        "holdout_max_absolute_error_percent": max(
            float(row["absolute_error_percent"]) for row in holdout
        ),
        "workload_rank_spearman": rank,
    }


def collect_total_records(
    cases: dict[str, Any],
    contract: dict[str, Any],
    simulation_root: Path,
    hardware_root: Path,
    *,
    allow_partial: bool,
) -> tuple[list[CurrentFPGATimingRecord], list[dict[str, Any]], list[str]]:
    clock_mhz = float(cases["clock_mhz"])
    records: list[CurrentFPGATimingRecord] = []
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []
    contract_profiles = {
        (entry["architecture"], entry["algorithm"]): entry
        for entry in contract["architecture_profiles"]
    }
    expected_plugin_sha256 = str(contract["simulator_plugin"]["sha256"])
    for algorithm, algorithm_spec in cases["algorithms"].items():
        aggregate_path = hardware_root / algorithm_spec["hardware_directory"] / "aggregate_3runs.tsv"
        aggregate_rows = {
            row["case"]: row for row in read_tsv(aggregate_path)
        }
        for dataset, role in cases["roles"].items():
            hardware_case = f"{dataset}_{algorithm_spec['hardware_case_suffix']}"
            hardware = aggregate_rows.get(hardware_case)
            if hardware is None:
                raise ValueError(f"missing hardware aggregate row: {hardware_case}")
            identity = validate_workload_identity(
                simulation_root,
                dataset,
                algorithm_spec["workload_algorithm"],
                hardware["graph"],
            )
            for architecture in ARCHITECTURES:
                profile_field = f"{architecture}_profile_id"
                expected_profile = algorithm_spec[profile_field]
                contract_entry = contract_profiles[(architecture, algorithm)]
                if contract_entry["profile_id"] != expected_profile:
                    raise ValueError(f"case/contract profile mismatch: {architecture}:{algorithm}")
                simulation_directories = algorithm_spec.get("simulation_directories", {})
                simulation_directory = simulation_directories.get(
                    architecture, algorithm_spec["simulation_directory"]
                )
                run_dir = (
                    simulation_root
                    / "runs_current_v1"
                    / dataset
                    / architecture
                    / simulation_directory
                )
                try:
                    result, result_path, manifest_path = load_simulator_result(run_dir)
                except FileNotFoundError:
                    missing.append(f"{architecture}:{algorithm}:{dataset}")
                    if allow_partial:
                        continue
                    raise
                manifest = read_json(manifest_path) if manifest_path else {}
                observed_profile = profile_id_of(result, manifest)
                if observed_profile != expected_profile:
                    raise ValueError(
                        f"profile mismatch for {architecture}:{algorithm}:{dataset}: "
                        f"{observed_profile} != {expected_profile}"
                    )
                observed_profile_sha256 = profile_sha256_of(result, manifest)
                if observed_profile_sha256 != contract_entry["sha256"]:
                    raise ValueError(
                        f"profile hash mismatch for {architecture}:{algorithm}:{dataset}"
                    )
                if manifest.get("sst_plugin_sha256") != expected_plugin_sha256:
                    raise ValueError(
                        f"plugin hash mismatch for {architecture}:{algorithm}:{dataset}"
                    )
                if float(result.get("core_mhz", manifest.get("core_mhz", 0))) != clock_mhz:
                    raise ValueError(f"clock mismatch: {run_dir}")
                target = cases["timing_targets"][architecture]
                hardware_ms = float(hardware[target["aggregate_field"]])
                if hardware_ms <= 0:
                    raise ValueError(f"non-positive hardware timing: {hardware_case}")
                records.append(
                    CurrentFPGATimingRecord(
                        architecture=architecture,
                        algorithm=algorithm,
                        profile_id=expected_profile,
                        dataset=dataset,
                        role=role,
                        simulator_cycles=float(result["cycles"]),
                        hardware_cycles=hardware_ms * clock_mhz * 1000.0,
                    )
                )
                evidence.append(
                    {
                        "architecture": architecture,
                        "algorithm": algorithm,
                        "dataset": dataset,
                        "role": role,
                        "profile_id": expected_profile,
                        "profile_sha256": observed_profile_sha256,
                        "sst_plugin_sha256": expected_plugin_sha256,
                        "simulator_result": str(result_path.resolve()),
                        "simulator_result_sha256": sha256_file(result_path),
                        "simulator_manifest": str(manifest_path.resolve()) if manifest_path else None,
                        "simulator_manifest_sha256": sha256_file(manifest_path) if manifest_path else None,
                        "hardware_aggregate": str(aggregate_path.resolve()),
                        "hardware_aggregate_sha256": sha256_file(aggregate_path),
                        "hardware_case": hardware_case,
                        "hardware_timing_field": target["aggregate_field"],
                        "hardware_observation": target["observation"],
                        **identity,
                    }
                )
    return records, evidence, missing


def analyze_total(
    records: list[CurrentFPGATimingRecord],
    frozen_models: dict[tuple[str, ...], Any] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[CurrentFPGATimingRecord]] = {}
    for record in records:
        grouped.setdefault(
            (record.architecture, record.algorithm, record.profile_id), []
        ).append(record)
    predictions: list[dict[str, object]] = []
    models: list[dict[str, Any]] = []
    summaries: list[dict[str, object]] = []
    for key in sorted(grouped):
        rows = sorted(grouped[key], key=lambda row: (row.role, row.dataset))
        if len(rows) != 4:
            continue
        if frozen_models is None:
            model = fit_total_scale(rows)
        else:
            model = frozen_models.get(key)
            if model is None:
                raise ValueError(f"missing frozen total model: {key}")
        group_predictions = total_prediction_rows(rows, model)
        predictions.extend(group_predictions)
        summaries.append(summarize_group(group_predictions))
        models.append(
            {
                **asdict(model),
                "profile_id": key[2],
                "fit_role": "calibration_only",
                "holdout_used_for_fit": False,
                "model_form": "hardware_cycles = scale * execution_driven_simulator_cycles",
            }
        )
    return predictions, summaries, models


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--simulation-root", type=Path)
    parser.add_argument("--hardware-root", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--frozen-models-dir", type=Path)
    args = parser.parse_args()

    cases = read_json(args.cases.resolve())
    contract_path = args.contract.resolve()
    contract = read_json(contract_path)
    if cases.get("status") != "frozen" or contract.get("status") != "frozen":
        raise ValueError("case and calibration contracts must be frozen")
    if cases.get("calibration_contract_id") != contract.get("contract_id"):
        raise ValueError("case manifest and calibration contract disagree")
    plugin_path = ROOT / contract["simulator_plugin"]["path"]
    if not plugin_path.is_file() or sha256_file(plugin_path) != contract[
        "simulator_plugin"
    ]["sha256"]:
        raise ValueError("frozen simulator plugin identity mismatch")
    simulation_root = (args.simulation_root or Path(cases["default_simulation_root"])).resolve()
    hardware_root = (args.hardware_root or Path(cases["default_hardware_root"])).resolve()
    frozen_models = None
    frozen_provenance = None
    if args.frozen_models_dir:
        frozen_models, frozen_provenance = load_frozen_scale_models(
            args.frozen_models_dir,
            kind="total",
            contract_id=contract["contract_id"],
            contract_sha256=sha256_file(contract_path),
            cases_sha256=sha256_file(args.cases.resolve()),
            plugin_sha256=contract["simulator_plugin"]["sha256"],
        )
    records, evidence, missing = collect_total_records(
        cases,
        contract,
        simulation_root,
        hardware_root,
        allow_partial=args.allow_partial,
    )
    predictions, summaries, models = analyze_total(records, frozen_models)
    expected_groups = len(ARCHITECTURES) * len(cases["algorithms"])
    thresholds = contract["manifest_gates"]["total_cycle"]
    checks = []
    for row in summaries:
        checks.append(
            {
                **row,
                "median_pass": float(row["holdout_median_absolute_error_percent"])
                <= float(thresholds["non_tiny_median_absolute_error_percent_max"]),
                "max_pass": float(row["holdout_max_absolute_error_percent"])
                <= float(thresholds["non_tiny_absolute_error_percent_max"]),
                "rank_pass": float(row["workload_rank_spearman"])
                >= float(thresholds["workload_rank_spearman_min"]),
            }
        )
    all_pass = (
        not missing
        and len(summaries) == expected_groups
        and all(row["median_pass"] and row["max_pass"] and row["rank_pass"] for row in checks)
    )
    status = "PASS" if all_pass else ("INCOMPLETE" if missing else "FAIL")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "total_cycle_rows.csv", predictions)
    write_csv(args.out_dir / "total_cycle_group_summary.csv", summaries)
    write_json(
        args.out_dir / "total_cycle_models.json",
        {
            "schema_version": 1,
            "status": status,
            "parameters_frozen": frozen_models is not None or all_pass,
            "parameters_frozen_before_holdout": frozen_models is not None,
            "models": models,
        },
    )
    coverage = [
        {
            "architecture": architecture,
            "algorithm": algorithm,
            "profile_id": next(
                entry["profile_id"]
                for entry in contract["architecture_profiles"]
                if entry["architecture"] == architecture and entry["algorithm"] == algorithm
            ),
            "calibration_cases": sum(
                row.architecture == architecture
                and row.algorithm == algorithm
                and row.role == "calibration"
                for row in records
            ),
            "holdout_cases": sum(
                row.architecture == architecture
                and row.algorithm == algorithm
                and row.role == "holdout"
                for row in records
            ),
        }
        for architecture in ARCHITECTURES
        for algorithm in cases["algorithms"]
    ]
    manifest = {
        "schema_version": 1,
        "gate_kind": "total_cycle",
        "contract_id": contract["contract_id"],
        "contract_sha256": sha256_file(contract_path),
        "status": status,
        "parameters_frozen": frozen_models is not None or all_pass,
        "parameters_frozen_before_holdout": frozen_models is not None,
        "correctness_gate": "PASS" if not missing else "INCOMPLETE",
        "workload_identity_pinned": not missing,
        "calibration_and_holdout_disjoint": True,
        "fit_policy": (
            "load immutable pre-holdout positive scale per architecture/algorithm"
            if frozen_models is not None
            else "one positive geometric-mean scale per architecture/algorithm; calibration rows only"
        ),
        "frozen_model_provenance": frozen_provenance,
        "timing_window": contract["timing_windows"]["device_dynamic"],
        "coverage": coverage,
        "threshold_checks": {
            "all_pass": all_pass,
            "required": thresholds,
            "groups": checks,
        },
        "missing_cases": sorted(missing),
        "evidence": evidence,
    }
    write_json(args.out_dir / "total_cycle_calibration.json", manifest)
    print(
        f"CURRENT_FPGA_TOTAL_CALIBRATION_{status} records={len(records)} "
        f"groups={len(summaries)}/{expected_groups} missing={len(missing)}"
    )
    return 0 if all_pass or (args.allow_partial and status == "INCOMPLETE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
