#!/usr/bin/env python3
"""Run simulator counterparts of the routed refactor31 FPGA probes."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.calibration.refactor31 import (  # noqa: E402
    REFACTOR31_CASES,
    write_refactor31_fixture,
)


DEFAULT_PROFILE = (
    ROOT / "configs" / "architectures" / "spine_refactor31_routed_native_v1.json"
)
DEFAULT_FPGA_SUMMARY = (
    ROOT
    / "docs"
    / "evidence"
    / "refactor31_fpga_calibration"
    / "refactor31_fpga_case_summary.csv"
)


def read_fpga_summary(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return {row["case"]: row for row in csv.DictReader(stream)}


def relative_error(predicted: int, measured: int) -> float:
    return (predicted - measured) / measured * 100.0


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--fpga-summary", type=Path, default=DEFAULT_FPGA_SUMMARY)
    parser.add_argument("--max-cycles", type=int, default=80_000_000)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--cases", nargs="+", choices=REFACTOR31_CASES)
    args = parser.parse_args()

    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = tuple(args.cases or REFACTOR31_CASES)
    fpga = read_fpga_summary(args.fpga_summary.resolve())
    rows: list[dict[str, Any]] = []
    for case in cases:
        workload = write_refactor31_fixture(
            output / "workloads" / f"{case}.slice", case
        )
        run_dir = output / "runs" / case
        command = [
            sys.executable,
            str(ROOT / "scripts" / "run_sst_spine_vertical.py"),
            "--out-dir",
            str(run_dir),
            "--scenario",
            "refactor31_probe",
            "--profile",
            str(args.profile.resolve()),
            "--workload",
            str(workload),
            "--max-cycles",
            str(args.max_cycles),
        ]
        if args.no_build:
            command.append("--no-build")
        subprocess.run(command, cwd=ROOT, check=True)
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        reader_cycles = int(summary["reader_end_cycles_per_round"][0]) - int(
            summary["reader_start_cycles_per_round"][0]
        )
        compute_cycles = int(summary["compute_end_cycles_per_round"][0]) - int(
            summary["compute_start_cycles_per_round"][0]
        )
        conv_cycles = max(
            int(summary["reader_end_cycles_per_round"][0]),
            int(summary["compute_end_cycles_per_round"][0]),
        ) - min(
            int(summary["reader_start_cycles_per_round"][0]),
            int(summary["compute_start_cycles_per_round"][0]),
        )
        measured = fpga[case]
        measured_reader = int(measured["median_reader_cycles"])
        measured_compute = int(measured["median_compute_cycles"])
        measured_conv = int(measured["median_conv_cycles"])
        rows.append(
            {
                "case": case,
                "role": "holdout" if case.endswith("many_tiles") else "calibration",
                "path": "fallback" if "_gate_" in case else "exact",
                "edges": summary["input_edges"],
                "active_sources": summary["reader_range_active_records"],
                "sim_reader_cycles": reader_cycles,
                "fpga_reader_cycles": measured_reader,
                "reader_error_pct": f"{relative_error(reader_cycles, measured_reader):.6f}",
                "sim_compute_cycles": compute_cycles,
                "fpga_compute_cycles": measured_compute,
                "compute_error_pct": f"{relative_error(compute_cycles, measured_compute):.6f}",
                "sim_conv_cycles": conv_cycles,
                "fpga_conv_cycles": measured_conv,
                "conv_error_pct": f"{relative_error(conv_cycles, measured_conv):.6f}",
                "correctness_mismatches": summary["correctness_mismatches"],
                "frontier_mismatches": summary["frontier_mismatches"],
                "reader_request_ledger_closed": int(
                    summary["reader_memory_requests_issued"]
                    == summary["reader_memory_requests_completed"]
                ),
                "compute_request_ledger_closed": int(
                    summary["compute_memory_requests_issued"]
                    == summary["compute_memory_requests_completed"]
                ),
                "sim_summary": str(run_dir / "summary.json"),
            }
        )

    write_csv(output / "refactor31_sim_fpga_comparison.csv", rows)
    evidence = {
        "schema_version": 1,
        "evidence_id": "refactor31_sim_fpga_mechanism_transfer_v1",
        "profile": str(args.profile.resolve()),
        "cases": len(rows),
        "calibration_cases": sum(row["role"] == "calibration" for row in rows),
        "holdout_cases": sum(row["role"] == "holdout" for row in rows),
        "all_simulator_correct": all(
            row["correctness_mismatches"] == 0
            and row["frontier_mismatches"] == 0
            for row in rows
        ),
        "claim_boundary": {
            "supported": [
                "matching_refactor31_exact_and_active_gate_fixture_execution",
                "simulator_internal_state_and_frontier_correctness",
                "reader_compute_mechanism_cycle_transfer_error_characterization",
            ],
            "not_supported": [
                "hardware_correctness_admission_for_original_logs",
                "medium_real_slice_cycle_transfer",
                "paper_owner_scheduler_fpga_calibration",
            ],
        },
    }
    (output / "evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"PASS cases={len(rows)} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
