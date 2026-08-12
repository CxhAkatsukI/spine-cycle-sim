#!/usr/bin/env python3
"""Freeze or validate the routed G+R update shard-control timing model."""

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
    median_float,
    read_json,
    unique_prefixed_record,
)
from spine_cycle_sim.calibration.current_fpga import (  # noqa: E402
    GrasuUpdateControlModel,
    GrasuUpdateControlRecord,
    fit_grasu_update_control_model,
    grasu_update_control_leave_one_dataset_out_rows,
    grasu_update_control_prediction_rows,
)


DEFAULT_CONTRACT = (
    ROOT / "configs/contracts/current_fpga_grasu_update_control_v13.json"
)
DEFAULT_OBSERVATION_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v13_update_observability_20260812"
)
DEFAULT_HARDWARE_ROOT = Path(
    "/home/chuxiao/grasu-regraph-integration/docs/evidence/sharded_k4_fullgraph_20260806"
)
DEFAULT_FROZEN = (
    ROOT / "docs/evaluation_refresh_20260810/calibration_v16_grasu_update_frozen"
)
HARDWARE_PREFIX = {
    "weighted_sssp": "WEIGHTED_PMA_NATIVE_SHARDED_TIMING",
    "connected_components": "CC_PMA_NATIVE_SHARDED_TIMING",
    "thresholded_residual_pagerank": "RESIDUAL_PR_PMA_NATIVE_SHARDED_TIMING",
}
HARDWARE_FIELD = {
    "weighted_sssp": "grasu_ms",
    "connected_components": "grasu_ms",
    "thresholded_residual_pagerank": "update_ms",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", encoding="ascii", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def validate_contract(contract_path: Path, contract: dict[str, Any]) -> None:
    if contract.get("status") != "frozen_before_holdout":
        raise ValueError("G+R update control contract is not frozen")
    for entry in (contract["plugin"], contract["case_contract"]):
        path = ROOT / entry["path"]
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise ValueError(f"frozen artifact mismatch: {path}")
    for entry in contract["profiles"].values():
        path = ROOT / entry["path"]
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise ValueError(f"frozen profile mismatch: {path}")
    if sha256_file(contract_path) == "":
        raise AssertionError("unreachable")


def load_model(path: Path) -> dict[str, GrasuUpdateControlModel]:
    payload = read_json(path)
    if payload.get("status") != "FROZEN_BEFORE_HOLDOUT":
        raise ValueError("G+R update model is not frozen")
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


def collect_records(
    *,
    contract: dict[str, Any],
    role: str,
    observation_root: Path,
    hardware_root: Path,
) -> tuple[list[GrasuUpdateControlRecord], list[dict[str, object]]]:
    case_contract = read_json(ROOT / contract["case_contract"]["path"])
    clock_mhz = float(contract["clock_mhz"])
    records: list[GrasuUpdateControlRecord] = []
    evidence: list[dict[str, object]] = []
    for dataset in contract["roles"][role]:
        for algorithm in contract["algorithms"]:
            result_path = observation_root / role / dataset / algorithm / "result.json"
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
            if not isinstance(observability, dict):
                raise ValueError(f"missing update observability: {result_path}")
            gates = contract["gates"]
            if (
                result.get("success") is not True
                or int(result.get("correctness_mismatches", -1))
                != gates["correctness_mismatches"]
                or result.get("memory_locality_ledger_match")
                is not gates["memory_locality_ledger_match"]
                or result.get("measurement_window") != gates["measurement_window"]
                or int(result.get("compute_cycles", -1)) != 0
                or manifest.get("sst_plugin_sha256")
                != contract["plugin"]["sha256"]
            ):
                raise ValueError(f"observation admission failed: {result_path}")
            algorithm_spec = case_contract["algorithms"][algorithm]
            logs = discover_hardware_logs(
                hardware_root, algorithm_spec, dataset, "grasu_regraph"
            )
            if len(logs) < 3:
                raise FileNotFoundError(
                    f"three hardware runs required: {dataset}:{algorithm}"
                )
            timing_records = [
                unique_prefixed_record(path, HARDWARE_PREFIX[algorithm])
                for path in logs
            ]
            hardware_cycles = (
                median_float(timing_records, HARDWARE_FIELD[algorithm])
                * clock_mhz
                * 1000.0
            )
            profile = contract["profiles"][algorithm]
            record = GrasuUpdateControlRecord(
                algorithm=algorithm,
                profile_id=profile["profile_id"],
                dataset=dataset,
                role=role,
                simulator_update_cycles=float(result["update_cycles"]),
                nonempty_destination_shards=int(
                    observability["destination_partitions_touched"]
                ),
                hardware_update_cycles=hardware_cycles,
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
                    "hardware_logs": [str(path) for path in logs],
                    "hardware_log_sha256": [sha256_file(path) for path in logs],
                }
            )
    return records, evidence


def summarize(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for algorithm in sorted({str(row["algorithm"]) for row in rows}):
        group = [row for row in rows if row["algorithm"] == algorithm]
        errors = [float(row["absolute_error_percent"]) for row in group]
        output.append(
            {
                "algorithm": algorithm,
                "role": group[0]["role"],
                "cases": len(group),
                "median_absolute_error_percent": statistics.median(errors),
                "max_absolute_error_percent": max(errors),
            }
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("freeze", "holdout"), required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--observation-root", type=Path, default=DEFAULT_OBSERVATION_ROOT
    )
    parser.add_argument("--hardware-root", type=Path, default=DEFAULT_HARDWARE_ROOT)
    parser.add_argument("--frozen-dir", type=Path, default=DEFAULT_FROZEN)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()
    contract_path = args.contract.resolve()
    contract = read_json(contract_path)
    validate_contract(contract_path, contract)
    role = "calibration" if args.mode == "freeze" else "holdout"
    records, evidence = collect_records(
        contract=contract,
        role=role,
        observation_root=args.observation_root.resolve(),
        hardware_root=args.hardware_root.resolve(),
    )
    out_dir = (
        args.frozen_dir.resolve()
        if args.mode == "freeze"
        else (args.out_dir or args.frozen_dir.parent / "calibration_v16_grasu_update_holdout").resolve()
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "freeze":
        models = []
        predictions = []
        loo_rows = []
        for algorithm in contract["algorithms"]:
            group = [row for row in records if row.algorithm == algorithm]
            model = fit_grasu_update_control_model(group)
            models.append(asdict(model))
            predictions.extend(grasu_update_control_prediction_rows(group, model))
            loo_rows.extend(grasu_update_control_leave_one_dataset_out_rows(group))
        calibration_limit = float(
            contract["gates"]["calibration_absolute_error_percent_max"]
        )
        loo_limit = float(
            contract["gates"][
                "calibration_leave_one_dataset_out_absolute_error_percent_max"
            ]
        )
        passed = all(
            float(row["absolute_error_percent"]) <= calibration_limit
            for row in predictions
        ) and all(
            float(row["absolute_error_percent"]) <= loo_limit for row in loo_rows
        )
        if not passed:
            raise ValueError("G+R update calibration development gates failed")
        model_path = out_dir / "frozen_grasu_update_control_models.json"
        write_json(
            model_path,
            {
                "schema_version": 1,
                "status": "FROZEN_BEFORE_HOLDOUT",
                "contract_id": contract["contract_id"],
                "contract_sha256": sha256_file(contract_path),
                "holdout_used_for_fit": False,
                "models": models,
            },
        )
        write_csv(out_dir / "calibration_predictions.csv", predictions)
        write_csv(out_dir / "leave_one_dataset_out.csv", loo_rows)
        write_json(
            out_dir / "freeze_manifest.json",
            {
                "schema_version": 1,
                "status": "FROZEN_BEFORE_HOLDOUT",
                "contract": str(contract_path),
                "contract_sha256": sha256_file(contract_path),
                "plugin_sha256": contract["plugin"]["sha256"],
                "model": str(model_path),
                "model_sha256": sha256_file(model_path),
                "calibration_summary": summarize(predictions),
                "evidence": evidence,
            },
        )
        print(f"GRASU_UPDATE_CONTROL_FROZEN out={out_dir}")
        return 0

    model_path = args.frozen_dir.resolve() / "frozen_grasu_update_control_models.json"
    models = load_model(model_path)
    predictions = []
    for algorithm in contract["algorithms"]:
        group = [row for row in records if row.algorithm == algorithm]
        predictions.extend(
            grasu_update_control_prediction_rows(group, models[algorithm])
        )
    summary = summarize(predictions)
    median_limit = float(
        contract["gates"]["holdout_median_absolute_error_percent_max"]
    )
    max_limit = float(contract["gates"]["holdout_absolute_error_percent_max"])
    passed = all(
        float(row["median_absolute_error_percent"]) <= median_limit
        and float(row["max_absolute_error_percent"]) <= max_limit
        for row in summary
    )
    write_csv(out_dir / "holdout_predictions.csv", predictions)
    write_json(
        out_dir / "holdout_manifest.json",
        {
            "schema_version": 1,
            "status": "PASS" if passed else "FAIL",
            "contract": str(contract_path),
            "contract_sha256": sha256_file(contract_path),
            "frozen_model": str(model_path),
            "frozen_model_sha256": sha256_file(model_path),
            "holdout_used_for_fit": False,
            "summary": summary,
            "evidence": evidence,
        },
    )
    print(f"GRASU_UPDATE_CONTROL_HOLDOUT status={'PASS' if passed else 'FAIL'} out={out_dir}")
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
