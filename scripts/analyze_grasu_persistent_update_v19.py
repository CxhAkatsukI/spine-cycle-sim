#!/usr/bin/env python3
"""Freeze and validate the routed G+R persistent warm-update timing model."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.calibration.current_fpga import (  # noqa: E402
    GrasuUpdateControlModel,
    GrasuUpdateControlRecord,
    fit_grasu_update_control_model,
    grasu_update_control_leave_one_dataset_out_rows,
    grasu_update_control_prediction_rows,
)


DEFAULT_CONTRACT = (
    ROOT / "configs/contracts/current_fpga_grasu_persistent_update_v19.json"
)
DEFAULT_SIMULATOR_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v13_update_observability_20260812"
)
DEFAULT_HARDWARE_ROOT = Path(
    "/data/tmp/chuxiao/grasu_update_only_calibration_1577c60"
)
ALGORITHM_TAG = {
    "weighted_sssp": "weighted_sssp",
    "connected_components": "connected_components",
    "thresholded_residual_pagerank": "residual_pagerank",
}
REPEAT_PATTERN = re.compile(
    r"^GRASU_SHARDED_UPDATE_REPEAT repeat=(?P<repeat>\d+) "
    r"final=(?P<final>[01]) update_ms=(?P<update_ms>[0-9.]+)"
    r"(?: barrier_ms=(?P<barrier_ms>[0-9.]+))?$"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", encoding="ascii", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return values


def parse_repeat_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = REPEAT_PATTERN.fullmatch(line)
        if match:
            rows.append(
                {
                    "repeat": int(match.group("repeat")),
                    "final": int(match.group("final")),
                    "update_ms": float(match.group("update_ms")),
                    "barrier_ms": (
                        float(match.group("barrier_ms"))
                        if match.group("barrier_ms") is not None
                        else None
                    ),
                }
            )
    return rows


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("status") != "frozen_before_transfer_observation":
        raise ValueError("persistent update contract is not frozen before transfer")
    for entry in (contract["plugin"], contract["case_contract"]):
        path = ROOT / entry["path"]
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise ValueError(f"frozen artifact mismatch: {path}")
    for entry in contract["profiles"].values():
        path = ROOT / entry["path"]
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise ValueError(f"frozen profile mismatch: {path}")
    if contract["model"].get("transfer_may_fit") is not False:
        raise ValueError("transfer rows must be excluded from fitting")


def simulator_result_path(root: Path, role: str, dataset: str, algorithm: str) -> Path:
    role_dir = "calibration" if role == "calibration" else "transfer"
    return root / role_dir / dataset / algorithm / "result.json"


def hardware_case_dir(root: Path, dataset: str, algorithm: str) -> Path:
    return root / f"{dataset}_{ALGORITHM_TAG[algorithm]}"


def collect_records(
    contract: dict[str, Any],
    *,
    role: str,
    simulator_root: Path,
    hardware_root: Path,
) -> tuple[list[GrasuUpdateControlRecord], list[dict[str, object]]]:
    records: list[GrasuUpdateControlRecord] = []
    evidence: list[dict[str, object]] = []
    warm_ids = [int(value) for value in contract["integration"]["warm_repeats"]]
    expected_repeat_ids = [int(contract["integration"]["cold_repeat"]), *warm_ids]
    for dataset in contract["roles"][role]:
        for algorithm in contract["algorithms"]:
            result_path = simulator_result_path(
                simulator_root, role, dataset, algorithm
            )
            result = read_json(result_path)
            manifest_path = next(
                path
                for path in (
                    result_path.parent / "run_manifest.json",
                    result_path.parent / "manifest.json",
                )
                if path.is_file()
            )
            manifest = read_json(manifest_path)
            observability = result.get("update_observability")
            gates = contract["gates"]
            profile = contract["profiles"][algorithm]
            if (
                result.get("success") is not True
                or result.get("measurement_window")
                != gates["simulator_measurement_window"]
                or int(result.get("compute_cycles", -1)) != 0
                or int(result.get("correctness_mismatches", -1))
                != gates["correctness_mismatches"]
                or result.get("memory_locality_ledger_match")
                is not gates["memory_locality_ledger_match"]
                or not isinstance(observability, dict)
                or manifest.get("status") != "PASS"
                or (
                    manifest.get("source_revision") is not None
                    and manifest.get("source_revision")
                    != contract["plugin"]["source_revision"]
                )
                or manifest.get("sst_plugin_sha256")
                != contract["plugin"]["sha256"]
                or (
                    manifest.get("profile_id") is not None
                    and manifest.get("profile_id") != profile["profile_id"]
                )
                or manifest.get("profile_sha256") != profile["sha256"]
            ):
                raise ValueError(f"simulator admission failed: {result_path}")
            case_dir = hardware_case_dir(hardware_root, dataset, algorithm)
            env_path = case_dir / "run.env"
            log_path = case_dir / "run.log"
            result_text_path = case_dir / "result.txt"
            env = parse_env(env_path)
            if (
                env.get("STATUS") != gates["hardware_status"]
                or env.get("REPO_HEAD") != contract["integration"]["repo_head"]
                or int(env.get("REPO_DIRTY", "-1"))
                != contract["integration"]["repo_dirty"]
                or env.get("MEASUREMENT_WINDOW") != "update_only"
                or sha256_file(log_path) != env.get("RUN_LOG_SHA256")
                or "status=PASS" not in result_text_path.read_text(encoding="utf-8")
            ):
                raise ValueError(f"hardware provenance admission failed: {case_dir}")
            repeat_rows = parse_repeat_rows(log_path)
            if [row["repeat"] for row in repeat_rows] != expected_repeat_ids:
                raise ValueError(f"unexpected repeat sequence: {case_dir}")
            if [row["final"] for row in repeat_rows] != [0] * (len(repeat_rows) - 1) + [1]:
                raise ValueError(f"unexpected final repeat marker: {case_dir}")
            warm_ms = [
                float(row["update_ms"])
                for row in repeat_rows
                if row["repeat"] in warm_ids
            ]
            warm_mean = statistics.fmean(warm_ms)
            warm_cv = statistics.pstdev(warm_ms) / warm_mean
            if warm_cv > gates["warm_repeat_cv_max"]:
                raise ValueError(f"warm repeat CV gate failed: {case_dir}: {warm_cv}")
            result_line = env.get("RESULT_LINE", "")
            if (
                f"pma_mismatches={gates['pma_mismatches']}" not in result_line
                or (
                    algorithm == "thresholded_residual_pagerank"
                    and f"degree_mismatches={gates['degree_mismatches']}"
                    not in result_line
                )
                or "first_repeat=cold_diagnostic" not in result_line
            ):
                raise ValueError(f"hardware state/correctness gate failed: {case_dir}")
            record = GrasuUpdateControlRecord(
                algorithm=algorithm,
                profile_id=contract["profiles"][algorithm]["profile_id"],
                dataset=dataset,
                role=role,
                simulator_update_cycles=float(result["update_cycles"]),
                nonempty_destination_shards=int(
                    observability["destination_partitions_touched"]
                ),
                hardware_update_cycles=(
                    statistics.median(warm_ms) * float(contract["clock_mhz"]) * 1000.0
                ),
            )
            records.append(record)
            evidence.append(
                {
                    "algorithm": algorithm,
                    "dataset": dataset,
                    "role": role,
                    "simulator_result": str(result_path.resolve()),
                    "simulator_result_sha256": sha256_file(result_path),
                    "simulator_manifest": str(manifest_path.resolve()),
                    "simulator_manifest_sha256": sha256_file(manifest_path),
                    "hardware_run_env": str(env_path.resolve()),
                    "hardware_run_env_sha256": sha256_file(env_path),
                    "hardware_run_log": str(log_path.resolve()),
                    "hardware_run_log_sha256": sha256_file(log_path),
                    "cold_update_ms": repeat_rows[0]["update_ms"],
                    "warm_update_ms": warm_ms,
                    "warm_update_median_ms": statistics.median(warm_ms),
                    "warm_update_cv": warm_cv,
                }
            )
    return records, evidence


def load_models(path: Path) -> dict[str, GrasuUpdateControlModel]:
    payload = read_json(path)
    if payload.get("status") != "FROZEN_BEFORE_TRANSFER_OBSERVATION":
        raise ValueError("persistent update model is not frozen before transfer")
    return {
        row["algorithm"]: GrasuUpdateControlModel(
            algorithm=row["algorithm"],
            profile_id=row["profile_id"],
            calibration_datasets=tuple(row["calibration_datasets"]),
            control_cycles_per_nonempty_shard=float(
                row["control_cycles_per_nonempty_shard"]
            ),
        )
        for row in payload["models"]
    }


def summarize(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for role in sorted({str(row["role"]) for row in rows}):
        for algorithm in sorted({str(row["algorithm"]) for row in rows}):
            values = [
                float(row["absolute_error_percent"])
                for row in rows
                if row["role"] == role and row["algorithm"] == algorithm
            ]
            if values:
                output.append(
                    {
                        "role": role,
                        "algorithm": algorithm,
                        "rows": len(values),
                        "median_absolute_error_percent": statistics.median(values),
                        "max_absolute_error_percent": max(values),
                    }
                )
    return output


def freeze(
    contract: dict[str, Any], simulator_root: Path, hardware_root: Path, out_dir: Path
) -> int:
    records, evidence = collect_records(
        contract,
        role="calibration",
        simulator_root=simulator_root,
        hardware_root=hardware_root,
    )
    models: list[GrasuUpdateControlModel] = []
    predictions: list[dict[str, object]] = []
    loo_rows: list[dict[str, object]] = []
    for algorithm in contract["algorithms"]:
        algorithm_records = [row for row in records if row.algorithm == algorithm]
        model = fit_grasu_update_control_model(algorithm_records)
        models.append(model)
        predictions.extend(grasu_update_control_prediction_rows(algorithm_records, model))
        loo_rows.extend(grasu_update_control_leave_one_dataset_out_rows(algorithm_records))
    max_error = max(float(row["absolute_error_percent"]) for row in predictions)
    max_loo = max(float(row["absolute_error_percent"]) for row in loo_rows)
    gates = contract["gates"]
    if max_error > gates["calibration_absolute_error_percent_max"]:
        raise ValueError(f"calibration error gate failed: {max_error}")
    if max_loo > gates["calibration_leave_one_dataset_out_absolute_error_percent_max"]:
        raise ValueError(f"calibration LOO gate failed: {max_loo}")
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "frozen_model.json"
    write_json(
        model_path,
        {
            "schema_version": 1,
            "status": "FROZEN_BEFORE_TRANSFER_OBSERVATION",
            "contract_id": contract["contract_id"],
            "timing_target": contract["integration"],
            "models": [asdict(model) for model in models],
        },
    )
    write_csv(out_dir / "calibration_predictions.csv", predictions)
    write_csv(out_dir / "calibration_leave_one_dataset_out.csv", loo_rows)
    write_json(out_dir / "calibration_evidence.json", evidence)
    write_json(
        out_dir / "manifest.json",
        {
            "status": "PASS",
            "contract": str(DEFAULT_CONTRACT.resolve()),
            "contract_sha256": sha256_file(DEFAULT_CONTRACT),
            "model": str(model_path.resolve()),
            "model_sha256": sha256_file(model_path),
            "transfer_results_used": False,
            "max_calibration_absolute_error_percent": max_error,
            "max_calibration_leave_one_dataset_out_absolute_error_percent": max_loo,
        },
    )
    print(f"PASS persistent update model frozen: {model_path}")
    return 0


def validate_transfer(
    contract: dict[str, Any],
    simulator_root: Path,
    hardware_root: Path,
    model_path: Path,
    out_dir: Path,
) -> int:
    models = load_models(model_path)
    records, evidence = collect_records(
        contract,
        role="transfer",
        simulator_root=simulator_root,
        hardware_root=hardware_root,
    )
    predictions: list[dict[str, object]] = []
    for algorithm in contract["algorithms"]:
        predictions.extend(
            grasu_update_control_prediction_rows(
                [row for row in records if row.algorithm == algorithm],
                models[algorithm],
            )
        )
    summary = summarize(predictions)
    gates = contract["gates"]
    passed = all(
        float(row["median_absolute_error_percent"])
        <= gates["transfer_median_absolute_error_percent_max"]
        and float(row["max_absolute_error_percent"])
        <= gates["transfer_absolute_error_percent_max"]
        for row in summary
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "transfer_predictions.csv", predictions)
    write_csv(out_dir / "transfer_summary.csv", summary)
    write_json(out_dir / "transfer_evidence.json", evidence)
    write_json(
        out_dir / "manifest.json",
        {
            "status": "PASS" if passed else "FAIL",
            "contract_sha256": sha256_file(DEFAULT_CONTRACT),
            "frozen_model_sha256": sha256_file(model_path),
            "model_refit": False,
        },
    )
    print(f"{'PASS' if passed else 'FAIL'} persistent update transfer validation")
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("freeze", "validate-transfer"), required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--simulator-root", type=Path, default=DEFAULT_SIMULATOR_ROOT)
    parser.add_argument("--hardware-root", type=Path, default=DEFAULT_HARDWARE_ROOT)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    contract = read_json(args.contract)
    validate_contract(contract)
    if args.mode == "freeze":
        return freeze(contract, args.simulator_root, args.hardware_root, args.out_dir)
    if args.model is None:
        parser.error("--model is required for validate-transfer")
    return validate_transfer(
        contract,
        args.simulator_root,
        args.hardware_root,
        args.model,
        args.out_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
