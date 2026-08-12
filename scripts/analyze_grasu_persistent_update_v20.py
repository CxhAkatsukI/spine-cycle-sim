#!/usr/bin/env python3
"""Freeze v20 persistent G+R launch timing and validate untouched SO/PK."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import statistics
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_grasu_persistent_update_v19 import (  # noqa: E402
    collect_records,
    sha256_file,
    summarize,
    write_csv,
    write_json,
)
from spine_cycle_sim.calibration.current_fpga import (  # noqa: E402
    GrasuPersistentLaunchModel,
    fit_grasu_persistent_launch_model,
    grasu_persistent_launch_leave_one_dataset_out_rows,
    grasu_persistent_launch_prediction_rows,
)

DEFAULT_CONTRACT = ROOT / "configs/contracts/current_fpga_grasu_persistent_update_v20.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("status") != "frozen_before_so_pk_holdout_observation":
        raise ValueError("v20 contract is not frozen before SO/PK holdout")
    if contract["model"].get("holdout_may_fit") is not False:
        raise ValueError("v20 holdout must never fit the model")
    for entry in (contract["plugin"], contract["case_contract"]):
        path = ROOT / entry["path"]
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise ValueError(f"frozen artifact mismatch: {path}")
    for entry in contract["profiles"].values():
        path = ROOT / entry["path"]
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise ValueError(f"frozen profile mismatch: {path}")


def role_contract(contract: dict[str, Any], datasets: list[str]) -> dict[str, Any]:
    payload = dict(contract)
    payload["roles"] = {"calibration": datasets, "transfer": datasets}
    return payload


def collect_development(
    contract: dict[str, Any], small_sim: Path, small_hw: Path,
    large_sim: Path, large_hw: Path,
):
    small, small_evidence = collect_records(
        role_contract(contract, contract["roles"]["development_small"]),
        role="calibration", simulator_root=small_sim, hardware_root=small_hw,
    )
    large, large_evidence = collect_records(
        role_contract(contract, contract["roles"]["development_transfer_failure"]),
        role="transfer", simulator_root=large_sim, hardware_root=large_hw,
    )
    return (
        [replace(row, role="calibration") for row in (*small, *large)],
        [dict(row, role="development") for row in (*small_evidence, *large_evidence)],
    )


def load_models(path: Path) -> dict[str, GrasuPersistentLaunchModel]:
    payload = read_json(path)
    if payload.get("status") != "FROZEN_BEFORE_SO_PK_HOLDOUT":
        raise ValueError("v20 model is not frozen before SO/PK holdout")
    return {
        row["algorithm"]: GrasuPersistentLaunchModel(
            algorithm=row["algorithm"], profile_id=row["profile_id"],
            development_datasets=tuple(row["development_datasets"]),
            batch_launch_cycles=float(row["batch_launch_cycles"]),
            post_first_shard_cycles=float(row["post_first_shard_cycles"]),
        )
        for row in payload["models"]
    }


def freeze(args: argparse.Namespace, contract: dict[str, Any]) -> int:
    records, evidence = collect_development(
        contract, args.small_sim_root, args.small_hw_root,
        args.large_sim_root, args.large_hw_root,
    )
    models = []
    predictions = []
    lodo = []
    for algorithm in contract["algorithms"]:
        rows = [row for row in records if row.algorithm == algorithm]
        model = fit_grasu_persistent_launch_model(rows)
        models.append(model)
        predictions.extend(grasu_persistent_launch_prediction_rows(rows, model))
        lodo.extend(grasu_persistent_launch_leave_one_dataset_out_rows(rows))
    gates = contract["gates"]
    max_error = max(float(row["absolute_error_percent"]) for row in predictions)
    max_lodo = max(float(row["absolute_error_percent"]) for row in lodo)
    if max_error > gates["development_absolute_error_percent_max"]:
        raise ValueError(f"development error gate failed: {max_error}")
    if max_lodo > gates["development_leave_one_dataset_out_absolute_error_percent_max"]:
        raise ValueError(f"development LODO gate failed: {max_lodo}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.out_dir / "frozen_model.json"
    write_json(model_path, {
        "schema_version": 1,
        "status": "FROZEN_BEFORE_SO_PK_HOLDOUT",
        "contract_id": contract["contract_id"],
        "models": [asdict(model) for model in models],
    })
    write_csv(args.out_dir / "development_predictions.csv", predictions)
    write_csv(args.out_dir / "development_leave_one_dataset_out.csv", lodo)
    write_json(args.out_dir / "development_evidence.json", evidence)
    write_json(args.out_dir / "manifest.json", {
        "status": "PASS", "contract_sha256": sha256_file(args.contract),
        "model_sha256": sha256_file(model_path), "holdout_results_used": False,
        "max_development_absolute_error_percent": max_error,
        "max_development_leave_one_dataset_out_absolute_error_percent": max_lodo,
    })
    print(f"PASS v20 frozen before SO/PK: {model_path}")
    return 0


def validate_holdout(args: argparse.Namespace, contract: dict[str, Any]) -> int:
    models = load_models(args.model)
    rows, evidence = collect_records(
        role_contract(contract, contract["roles"]["holdout"]), role="transfer",
        simulator_root=args.holdout_sim_root, hardware_root=args.holdout_hw_root,
    )
    predictions = []
    for algorithm in contract["algorithms"]:
        algorithm_rows = [replace(row, role="holdout") for row in rows if row.algorithm == algorithm]
        predictions.extend(grasu_persistent_launch_prediction_rows(algorithm_rows, models[algorithm]))
    summary = summarize(predictions)
    gates = contract["gates"]
    passed = all(
        float(row["median_absolute_error_percent"]) <= gates["holdout_median_absolute_error_percent_max"]
        and float(row["max_absolute_error_percent"]) <= gates["holdout_absolute_error_percent_max"]
        for row in summary
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "holdout_predictions.csv", predictions)
    write_csv(args.out_dir / "holdout_summary.csv", summary)
    write_json(args.out_dir / "holdout_evidence.json", [dict(row, role="holdout") for row in evidence])
    write_json(args.out_dir / "manifest.json", {
        "status": "PASS" if passed else "FAIL",
        "contract_sha256": sha256_file(args.contract),
        "frozen_model_sha256": sha256_file(args.model),
        "model_refit": False,
    })
    print(f"{'PASS' if passed else 'FAIL'} v20 SO/PK holdout")
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("freeze", "validate-holdout"), required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--small-sim-root", type=Path, default=Path("/data/tmp/chuxiao/evaluation_refresh_current_fpga_v19_persistent_update_20260812"))
    parser.add_argument("--small-hw-root", type=Path, default=Path("/data/tmp/chuxiao/grasu_update_only_calibration_1577c60"))
    parser.add_argument("--large-sim-root", type=Path, default=Path("/data/tmp/chuxiao/evaluation_refresh_current_fpga_v19_streaming_transfer_20260812"))
    parser.add_argument("--large-hw-root", type=Path, default=Path("/data/tmp/chuxiao/grasu_update_only_transfer_1577c60"))
    parser.add_argument("--holdout-sim-root", type=Path)
    parser.add_argument("--holdout-hw-root", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.contract = args.contract.resolve()
    contract = read_json(args.contract)
    validate_contract(contract)
    if args.mode == "freeze":
        return freeze(args, contract)
    if not all((args.holdout_sim_root, args.holdout_hw_root, args.model)):
        parser.error("validate-holdout requires holdout roots and --model")
    return validate_holdout(args, contract)


if __name__ == "__main__":
    raise SystemExit(main())
