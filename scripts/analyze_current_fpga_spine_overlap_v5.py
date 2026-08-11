#!/usr/bin/env python3
"""Fit and validate the frozen overlap-aware Spine FPGA timing model."""

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
    spine_structural_work_row,
    unique_prefixed_record,
)
from spine_cycle_sim.calibration.current_fpga import (  # noqa: E402
    CurrentFPGAOverlapRecord,
    fit_overlap_timing_model,
    overlap_prediction_rows,
    spearman_rank_correlation,
)


DEFAULT_CONTRACT = ROOT / "configs/contracts/current_fpga_spine_overlap_cases_v5.json"
DEFAULT_INDEX = ROOT / "docs/evidence/current_fpga_spine_overlap_index_v5.json"
DEFAULT_OUT = ROOT / "docs/evaluation_refresh_20260810/calibration_v5_overlap"


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


def summed(result: dict[str, Any], name: str) -> float:
    value = result.get(name, 0)
    if isinstance(value, list):
        return float(sum(float(item) for item in value))
    return float(value)


def median_field(records: list[dict[str, str]], field: str) -> float:
    values = [float(record[field]) for record in records]
    if len(values) != 3 or min(values) <= 0:
        raise ValueError(f"three positive hardware observations required for {field}")
    return statistics.median(values)


def load_admitted_result(
    run_dir: Path, contract: dict[str, Any]
) -> tuple[dict[str, Any], Path, Path]:
    result_path = run_dir / "result.json"
    manifest_path = next(
        (
            run_dir / name
            for name in ("run_manifest.json", "manifest.json", "summary.json")
            if (run_dir / name).is_file()
        ),
        run_dir / "summary.json",
    )
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
    profile = contract["profile"]
    observed_profile = result.get("architecture_profile_id") or manifest.get(
        "architecture_profile_id", manifest.get("profile_id")
    )
    if observed_profile != profile["profile_id"]:
        raise ValueError(f"profile mismatch: {run_dir}")
    observed_profile_sha = manifest.get("architecture_profile_sha256") or manifest.get(
        "profile_sha256", result.get("architecture_profile_sha256")
    )
    if observed_profile_sha != profile["sha256"]:
        raise ValueError(f"profile hash mismatch: {run_dir}")
    if manifest.get("sst_plugin_sha256") != contract["simulator_plugin"]["sha256"]:
        raise ValueError(f"plugin mismatch: {run_dir}")
    return result, result_path, manifest_path


def component_summary(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for role in ("calibration", "holdout"):
        selected = [row for row in rows if row["role"] == role]
        if not selected:
            continue
        for component in ("maintenance", "reader", "compute", "iterative_span", "total"):
            errors = [
                float(row[f"{component}_absolute_error_percent"])
                for row in selected
            ]
            predicted = [float(row[f"predicted_{component}_cycles"]) for row in selected]
            hardware_field = (
                "hardware_total_cycles"
                if component == "total"
                else f"hardware_{component}_cycles"
            )
            observed = [float(row[hardware_field]) for row in selected]
            summaries.append(
                {
                    "architecture": "spine",
                    "algorithm": "weighted_sssp",
                    "role": role,
                    "component": component,
                    "cases": len(selected),
                    "median_absolute_error_percent": statistics.median(errors),
                    "max_absolute_error_percent": max(errors),
                    "rank_spearman": (
                        spearman_rank_correlation(predicted, observed)
                        if len(selected) >= 2 and len(set(predicted)) > 1 and len(set(observed)) > 1
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
        raise ValueError("v5 contract was not frozen before holdout execution")
    if index.get("contract_id") != contract.get("contract_id"):
        raise ValueError("evidence index and contract disagree")
    plugin_path = ROOT / contract["simulator_plugin"]["path"]
    profile_path = ROOT / contract["profile"]["path"]
    if sha256_file(plugin_path) != contract["simulator_plugin"]["sha256"]:
        raise ValueError("frozen plugin identity mismatch")
    if sha256_file(profile_path) != contract["profile"]["sha256"]:
        raise ValueError("frozen profile identity mismatch")

    expected = {
        (dataset, role)
        for role in ("calibration", "holdout")
        for dataset in contract["roles"][role]
    }
    indexed = {(row["dataset"], row["role"]): row for row in index["rows"]}
    if len(indexed) != len(index["rows"]):
        raise ValueError("duplicate evidence-index row")
    if set(indexed) - expected:
        raise ValueError(f"unfrozen evidence rows: {sorted(set(indexed) - expected)}")
    missing = sorted(expected - set(indexed))
    if missing and not args.allow_partial:
        raise ValueError(f"missing frozen evidence rows: {missing}")

    clock_mhz = float(contract["clock_mhz"])
    records: list[CurrentFPGAOverlapRecord] = []
    evidence_rows: list[dict[str, object]] = []
    structural_rows: list[dict[str, object]] = []
    ledger_rows: list[dict[str, object]] = []
    for dataset, role in sorted(set(indexed) & expected):
        entry = indexed[(dataset, role)]
        run_dir = Path(entry["run_dir"]).resolve()
        result, result_path, manifest_path = load_admitted_result(run_dir, contract)
        hardware_logs = [Path(path).resolve() for path in entry["hardware_logs"]]
        if len(hardware_logs) != 3 or any(not path.is_file() for path in hardware_logs):
            raise ValueError(f"three hardware logs required for {dataset}")
        timing = [unique_prefixed_record(path, "SPINE_HW_TIMING") for path in hardware_logs]
        rounds = int(result["rounds"])
        cache_bytes = summed(result, "reader_level_cache_bytes_per_round")
        if cache_bytes % 8 != 0:
            raise ValueError(f"non-integral level-cache words: {dataset}")
        active_scan_words = sum(
            summed(result, name)
            for name in (
                "compute_active_emit_scan_words_per_round",
                "compute_sparse_store_scan_words_per_round",
                "compute_tile_active_clear_words_per_round",
            )
        )
        record = CurrentFPGAOverlapRecord(
            "spine",
            "weighted_sssp",
            contract["profile"]["profile_id"],
            dataset,
            role,
            rounds,
            float(result["maintenance_cycles"]),
            summed(result, "reader_active_cycles_per_round"),
            summed(result, "compute_active_cycles_per_round"),
            summed(result, "reader_memory_requests_issued_per_round"),
            cache_bytes / 8.0,
            active_scan_words,
            summed(result, "processed_edges_per_round"),
            median_field(timing, "maintenance_kernel_ms") * clock_mhz * 1000.0,
            median_field(timing, "reader_ms") * clock_mhz * 1000.0,
            median_field(timing, "compute_ms") * clock_mhz * 1000.0,
            median_field(timing, "kernel_span_ms") * clock_mhz * 1000.0,
        )
        records.append(record)
        structural_rows.append(
            spine_structural_work_row(
                "weighted_sssp", dataset, role, result, result_path, hardware_logs, timing
            )
        )
        ledger_rows.append(
            memory_ledger_row(
                "spine", "weighted_sssp", dataset, role, result, result_path
            )
        )
        evidence_rows.append(
            {
                "dataset": dataset,
                "role": role,
                "run_dir": str(run_dir),
                "result_sha256": sha256_file(result_path),
                "manifest_sha256": sha256_file(manifest_path),
                "hardware_logs": [str(path) for path in hardware_logs],
                "hardware_log_sha256": [sha256_file(path) for path in hardware_logs],
            }
        )

    predictions: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    model_payload: dict[str, object] | None = None
    calibration_count = len(contract["roles"]["calibration"])
    if sum(record.role == "calibration" for record in records) == calibration_count:
        model = fit_overlap_timing_model(records)
        predictions = overlap_prediction_rows(records, model)
        summaries = component_summary(predictions)
        model_payload = {**asdict(model), "fit_role": "calibration_only"}
    elif not args.allow_partial:
        raise ValueError("complete calibration set required")

    holdout_total = next(
        (
            row
            for row in summaries
            if row["role"] == "holdout" and row["component"] == "total"
        ),
        None,
    )
    thresholds = contract["thresholds"]
    holdout_pass = bool(
        holdout_total
        and float(holdout_total["median_absolute_error_percent"])
        <= float(thresholds["holdout_median_absolute_error_percent_max"])
        and float(holdout_total["max_absolute_error_percent"])
        <= float(thresholds["holdout_absolute_error_percent_max"])
        and (
            holdout_total["rank_spearman"] is None
            or float(holdout_total["rank_spearman"])
            >= float(thresholds["rank_spearman_min"])
        )
    )
    complete = not missing and model_payload is not None
    structural_pass = bool(
        structural_rows and all(row["status"] == "PASS" for row in structural_rows)
    )
    ledger_pass = bool(ledger_rows and all(row["status"] == "PASS" for row in ledger_rows))
    status = (
        "PASS"
        if complete and holdout_pass and structural_pass and ledger_pass
        else ("INCOMPLETE" if not complete else "FAIL")
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "spine_overlap_rows.csv", predictions)
    write_csv(args.out_dir / "spine_overlap_group_summary.csv", summaries)
    write_json(
        args.out_dir / "spine_overlap_model.json",
        {"status": status, "model": model_payload},
    )
    write_json(
        args.out_dir / "spine_overlap_structural_validation.json",
        {"status": "PASS" if structural_pass else "FAIL", "rows": structural_rows},
    )
    write_json(
        args.out_dir / "spine_overlap_memory_ledger_validation.json",
        {"status": "PASS" if ledger_pass else "FAIL", "rows": ledger_rows},
    )
    write_json(
        args.out_dir / "spine_overlap_calibration.json",
        {
            "schema_version": 1,
            "status": status,
            "parameters_frozen": complete,
            "contract_id": contract["contract_id"],
            "contract_sha256": sha256_file(contract_path),
            "evidence_index_sha256": sha256_file(index_path),
            "calibration_and_holdout_disjoint": True,
            "hardware_reader_compute_intervals_summed": False,
            "missing": [list(item) for item in missing],
            "holdout_total_pass": holdout_pass,
            "summaries": summaries,
            "evidence": evidence_rows,
        },
    )
    print(
        f"CURRENT_FPGA_SPINE_OVERLAP_{status} rows={len(records)} "
        f"missing={len(missing)} holdout_pass={holdout_pass}"
    )
    return 0 if status == "PASS" or (args.allow_partial and status == "INCOMPLETE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
