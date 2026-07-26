#!/usr/bin/env python3
"""Run source-matched candidate-10 maintenance cases through SST-HBM."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.candidate10_workloads import (  # noqa: E402
    materialize_candidate10_workloads,
)


DEFAULT_PROFILE = (
    ROOT / "configs/architectures/spine_candidate10_one_pass_1e61fc0.json"
)
DEFAULT_HW_EVIDENCE = (
    ROOT / "docs/evidence/spine_candidate10_hw_20260725/correctness_cases.csv"
)
MATRIX_FIELDS = (
    "case_id",
    "evidence_case",
    "role",
    "vertices",
    "input_edges",
    "unique_sources",
    "classify_blocks",
    "simulated_cycles",
    "hardware_maint_ms",
    "hardware_cycles",
    "raw_error_pct",
    "backend_requests",
    "dram_requests",
    "sst_host_wall_seconds",
    "slice_sha256",
    "status",
)


def load_hardware_timing(path: Path) -> dict[str, float]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    timing = {}
    for row in rows:
        value = row.get("maint_ms", "")
        if value:
            timing[row["evidence_case"]] = float(value)
    return timing


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=MATRIX_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--hardware-evidence", type=Path, default=DEFAULT_HW_EVIDENCE)
    parser.add_argument("--roles", default="calibration,holdout")
    parser.add_argument("--cases", default="")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--max-cycles", type=int, default=10_000_000)
    args = parser.parse_args()

    roles = tuple(role for role in args.roles.split(",") if role)
    selected_cases = frozenset(case for case in args.cases.split(",") if case)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    workload_manifest = materialize_candidate10_workloads(
        args.out_dir / "workloads", roles=roles
    )
    cases = [
        case
        for case in workload_manifest["cases"]
        if not selected_cases or case["case_id"] in selected_cases
    ]
    if selected_cases != {case["case_id"] for case in cases} and selected_cases:
        missing = selected_cases - {case["case_id"] for case in cases}
        raise SystemExit(f"unknown or role-excluded cases: {sorted(missing)}")
    hardware = load_hardware_timing(args.hardware_evidence)
    missing_hardware = [
        case["evidence_case"]
        for case in cases
        if case["evidence_case"] not in hardware
    ]
    if missing_hardware:
        raise SystemExit(f"hardware timing is missing: {missing_hardware}")
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j4"], cwd=ROOT, check=True)

    rows: list[dict[str, object]] = []
    for case in cases:
        run_dir = args.out_dir / "runs" / case["case_id"]
        command = [
            sys.executable,
            str(ROOT / "scripts/run_sst_spine_vertical.py"),
            "--out-dir",
            str(run_dir),
            "--profile",
            str(args.profile),
            "--scenario",
            "candidate10_maintenance",
            "--validation-mode",
            "generic",
            "--workload",
            case["slice"],
            "--max-cycles",
            str(args.max_cycles),
            "--no-build",
        ]
        started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        wall = time.monotonic() - started
        (run_dir / "matrix_runner.log").write_text(
            completed.stdout, encoding="utf-8"
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"candidate case {case['case_id']} failed; see "
                f"{run_dir / 'matrix_runner.log'}"
            )
        result = json.loads((run_dir / "summary.json").read_text())
        hardware_ms = hardware[case["evidence_case"]]
        hardware_cycles = hardware_ms * 150_000.0
        simulated_cycles = float(result["maintenance_cycles"])
        rows.append(
            {
                "case_id": case["case_id"],
                "evidence_case": case["evidence_case"],
                "role": case["role"],
                "vertices": case["vertices"],
                "input_edges": case["edges"],
                "unique_sources": result["maintenance_unique_sources"],
                "classify_blocks": result[
                    "maintenance_candidate_classify_blocks"
                ],
                "simulated_cycles": int(simulated_cycles),
                "hardware_maint_ms": hardware_ms,
                "hardware_cycles": hardware_cycles,
                "raw_error_pct": 100.0
                * (simulated_cycles - hardware_cycles)
                / hardware_cycles,
                "backend_requests": result["backend_requests"],
                "dram_requests": result["dram_reads"] + result["dram_writes"],
                "sst_host_wall_seconds": wall,
                "slice_sha256": case["slice_sha256"],
                "status": "PASS",
            }
        )
        write_rows(args.out_dir / "matrix.csv", rows)
        print(
            f"PASS {case['case_id']}: sim={simulated_cycles:.0f} "
            f"hw={hardware_cycles:.0f} cycles"
        )
    manifest = {
        "schema_version": 1,
        "claim": "matched_candidate10_sst_hardware_maintenance_matrix",
        "profile": str(args.profile.resolve()),
        "hardware_evidence": str(args.hardware_evidence.resolve()),
        "frequency_mhz": 150.0,
        "roles": list(roles),
        "cases": len(rows),
        "calibration_cases": [row["case_id"] for row in rows if row["role"] == "calibration"],
        "holdout_cases": [row["case_id"] for row in rows if row["role"] == "holdout"],
        "status": "PASS",
    }
    (args.out_dir / "matrix_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
