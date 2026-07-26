#!/usr/bin/env python3
"""Collect RTL, simulator A/B, and hardware evidence for the L0 writer schedule."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ORACLE = (
    ROOT / "docs/evidence/candidate10_l0_writer_rtl_oracle_20260726"
)
DEFAULT_SCHEDULE_ON = (
    ROOT / "results/candidate10_l0_writer_rtl_schedule_on_final_20260726"
    / "summary.json"
)
DEFAULT_SCHEDULE_OFF = (
    ROOT / "results/candidate10_l0_writer_rtl_schedule_off_final_20260726"
    / "summary.json"
)
DEFAULT_HW_MATRIX = (
    ROOT / "results/candidate10_l0_writer_rtl_schedule_hw_matrix_20260726"
    / "matrix.csv"
)
DEFAULT_BASELINE_MATRIX = (
    ROOT / "results/candidate10_grouped_schedule_full_20260726/matrix.csv"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_oracle(path: Path) -> dict[str, object]:
    rows = read_csv(path / "l0_writer_oracle.csv")
    manifest = read_json(path / "manifest.json")
    if not manifest.get("all_pass") or any(row["status"] != "PASS" for row in rows):
        raise RuntimeError("RTL oracle contains a failing case")

    valid_ideal = [
        row for row in rows
        if int(row["stall_period"]) == 0
        and row["expect_family_local_contract_failure"].lower() == "false"
    ]
    prediction_errors = [
        int(row["writer_rtl_min_prediction_error_cycles"])
        for row in valid_ideal
    ]
    stalled = [row for row in rows if int(row["stall_period"]) != 0]
    return {
        "cases": len(rows),
        "valid_ideal_cases": len(valid_ideal),
        "negative_contract_cases": sum(
            row["expect_family_local_contract_failure"].lower() == "true"
            for row in rows
        ),
        "backpressure_cases": len(stalled),
        "max_abs_prediction_error_cycles": max(
            (abs(value) for value in prediction_errors), default=0
        ),
        "backpressure": [
            {
                "case_id": row["case_id"],
                "ideal_case_id": row["ideal_case_id"],
                "cycles": int(row["cycles"]),
                "delta_cycles": int(row["backpressure_delta_cycles"]),
                "slowdown": float(row["backpressure_slowdown"]),
            }
            for row in stalled
        ],
        "oracle_csv_sha256": sha256(path / "l0_writer_oracle.csv"),
        "oracle_manifest_sha256": sha256(path / "manifest.json"),
        "frozen_xo_sha256": manifest["xo_sha256"],
    }


def summarize_ab(on_path: Path, off_path: Path) -> dict[str, object]:
    enabled = read_json(on_path)
    disabled = read_json(off_path)
    for label, summary in (("enabled", enabled), ("disabled", disabled)):
        if summary.get("status") != "PASS" or not summary.get("success"):
            raise RuntimeError(f"SST A/B {label} run did not pass")
    if not enabled.get("candidate_l0_writer_rtl_schedule"):
        raise RuntimeError("enabled A/B run has writer schedule disabled")
    if disabled.get("candidate_l0_writer_rtl_schedule"):
        raise RuntimeError("disabled A/B run has writer schedule enabled")
    if enabled["backend_requests"] != disabled["backend_requests"]:
        raise RuntimeError("writer control schedule changed backend request count")
    if enabled["backend_traffic"] != disabled["backend_traffic"]:
        raise RuntimeError("writer control schedule changed backend traffic")

    selected = (
        "cycles",
        "maintenance_cycles",
        "backend_requests",
        "dram_reads",
        "dram_writes",
        "dram_activates",
        "dram_read_row_hits",
        "dram_write_row_hits",
        "maintenance_l0_writer_rtl_schedule_invocations",
        "maintenance_l0_writer_rtl_min_cycles",
        "maintenance_l0_writer_rtl_padding_cycles",
        "maintenance_l0_writer_rtl_memory_overrun_cycles",
    )
    return {
        "enabled": {key: enabled[key] for key in selected},
        "disabled": {key: disabled[key] for key in selected},
        "cycle_delta": int(enabled["cycles"]) - int(disabled["cycles"]),
        "request_count_equal": True,
        "traffic_equal": True,
        "enabled_summary_sha256": sha256(on_path),
        "disabled_summary_sha256": sha256(off_path),
    }


def summarize_hardware(matrix_path: Path, baseline_path: Path) -> dict[str, object]:
    rows = read_csv(matrix_path)
    baseline_rows = read_csv(baseline_path)
    if any(row["status"] != "PASS" for row in rows):
        raise RuntimeError("hardware alignment matrix contains a failing case")
    baseline = {row["case_id"]: row for row in baseline_rows}
    if set(baseline) != {row["case_id"] for row in rows}:
        raise RuntimeError("writer and baseline hardware matrices use different cases")

    cases: list[dict[str, object]] = []
    grouped_errors: dict[str, list[float]] = {}
    for row in rows:
        case_id = row["case_id"]
        old = baseline[case_id]
        role = row["role"]
        error = float(row["raw_error_pct"])
        grouped_errors.setdefault(role, []).append(abs(error))
        cases.append({
            "case_id": case_id,
            "role": role,
            "input_edges": int(row["input_edges"]),
            "unique_sources": int(row["unique_sources"]),
            "active_families": int(row["classify_blocks"]),
            "hardware_cycles": float(row["hardware_cycles"]),
            "baseline_simulated_cycles": int(old["simulated_cycles"]),
            "writer_simulated_cycles": int(row["simulated_cycles"]),
            "writer_cycle_delta": (
                int(row["simulated_cycles"]) - int(old["simulated_cycles"])
            ),
            "writer_raw_error_pct": error,
        })
    return {
        "cases": cases,
        "median_abs_error_pct_by_role": {
            role: median(values) for role, values in sorted(grouped_errors.items())
        },
        "matrix_sha256": sha256(matrix_path),
        "baseline_matrix_sha256": sha256(baseline_path),
    }


def collect(
    oracle_dir: Path,
    schedule_on: Path,
    schedule_off: Path,
    hw_matrix: Path,
    baseline_matrix: Path,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "claim": "candidate10_l0_writer_control_schedule_alignment",
        "rtl_oracle": summarize_oracle(oracle_dir),
        "execution_driven_ab": summarize_ab(schedule_on, schedule_off),
        "hardware_holdout": summarize_hardware(hw_matrix, baseline_matrix),
        "claim_boundary": {
            "modeled": [
                "Candidate10 L0 writer structural control lower bound",
                "payload-backed child requests and response dependencies",
                "finite request FIFOs, burst splitting, outstanding limits, and backpressure",
                "concurrent writer-control and memory completion",
            ],
            "remaining": [
                "outer family-range and kernel-wrapper control schedule",
                "cycle-exact Vitis child-to-m_axi adapter arbitration",
                "U55C external AXI interconnect and HBM contention calibration",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle-dir", type=Path, default=DEFAULT_ORACLE)
    parser.add_argument("--schedule-on", type=Path, default=DEFAULT_SCHEDULE_ON)
    parser.add_argument("--schedule-off", type=Path, default=DEFAULT_SCHEDULE_OFF)
    parser.add_argument("--hw-matrix", type=Path, default=DEFAULT_HW_MATRIX)
    parser.add_argument("--baseline-matrix", type=Path, default=DEFAULT_BASELINE_MATRIX)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    evidence = collect(
        args.oracle_dir.resolve(),
        args.schedule_on.resolve(),
        args.schedule_off.resolve(),
        args.hw_matrix.resolve(),
        args.baseline_matrix.resolve(),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "PASS candidate10_l0_writer_schedule_alignment: "
        f"oracle={evidence['rtl_oracle']['cases']} "
        f"ab_delta={evidence['execution_driven_ab']['cycle_delta']} "
        f"hardware={len(evidence['hardware_holdout']['cases'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
