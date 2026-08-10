#!/usr/bin/env python3
"""Fit the routed K4-shared FullPR event envelope from realized work."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.calibration.k4_fpga import (  # noqa: E402
    K4CaseSpec,
    K4MicrobenchSpec,
    fit_k4_fullpr_component_model,
    k4_component_prediction_rows,
    k4_group_summary,
    load_k4_microbench_records,
    load_k4_timing_records,
)


def parse_case(value: str) -> K4CaseSpec:
    fields = value.split(":", 2)
    if len(fields) != 3:
        raise argparse.ArgumentTypeError("case must be NAME:ROLE:MANIFEST")
    name, role, manifest = fields
    if role not in {"calibration", "holdout"}:
        raise argparse.ArgumentTypeError("case role must be calibration or holdout")
    return K4CaseSpec(name, role, Path(manifest))


def parse_microbench(value: str) -> K4MicrobenchSpec:
    fields = value.split(":", 3)
    if len(fields) != 4:
        raise argparse.ArgumentTypeError(
            "microbench must be NAME:ROLE:SIM_MANIFEST:HARDWARE_RUN_DIR"
        )
    name, role, manifest, run_dir = fields
    if role not in {"calibration", "holdout"}:
        raise argparse.ArgumentTypeError(
            "microbenchmark role must be calibration or holdout"
        )
    return K4MicrobenchSpec(name, role, Path(manifest), Path(run_dir))


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="append", type=Path, required=True)
    parser.add_argument("--case", action="append", type=parse_case, required=True)
    parser.add_argument(
        "--microbench", action="append", type=parse_microbench, default=[]
    )
    parser.add_argument("--clock-mhz", type=float, default=150.0)
    parser.add_argument("--holdout-max-error-pct", type=float, default=20.0)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    records = load_k4_timing_records(
        args.summary, args.case, clock_mhz=args.clock_mhz
    )
    records.extend(
        load_k4_microbench_records(args.microbench, clock_mhz=args.clock_mhz)
    )
    model = fit_k4_fullpr_component_model(records)
    predictions = k4_component_prediction_rows(records, model)
    summary = k4_group_summary(predictions)
    holdout = next(row for row in summary if row["role"] == "holdout")
    passed = (
        float(holdout["calibrated_max_absolute_error_pct"])
        <= args.holdout_max_error_pct
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_tsv(args.out_dir / "predictions.tsv", predictions)
    write_tsv(args.out_dir / "group_summary.tsv", summary)
    (args.out_dir / "model.json").write_text(
        json.dumps(
            {
                **asdict(model),
                "fit_role": "calibration_only",
                "holdout_used_for_fit": False,
                "semantic": "fixed + vertices + executed PMA slots across all FullPR rounds",
                "limitations": [
                    "The target is a routed OpenCL event envelope, not an on-kernel cycle counter.",
                    "The component envelope preserves the execution-driven simulator's raw counters.",
                    "Transfer beyond the measured FullPR topology and scale domain requires new holdout evidence.",
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "status": "PASS" if passed else "FAIL",
                "claim_class": model.claim_class,
                "hardware_summaries": [
                    {"path": str(path.resolve()), "sha256": sha256(path.resolve())}
                    for path in args.summary
                ],
                "simulation_manifests": [
                    {
                        "case": case.case,
                        "role": case.role,
                        "path": str(case.simulation_manifest.resolve()),
                        "sha256": sha256(case.simulation_manifest.resolve()),
                    }
                    for case in args.case
                ],
                "microbenchmarks": [
                    {
                        "case": case.case,
                        "role": case.role,
                        "simulation_manifest": str(case.simulation_manifest.resolve()),
                        "simulation_manifest_sha256": sha256(
                            case.simulation_manifest.resolve()
                        ),
                        "hardware_summary": str(
                            case.hardware_run_dir.resolve() / "summary.tsv"
                        ),
                        "hardware_summary_sha256": sha256(
                            case.hardware_run_dir.resolve() / "summary.tsv"
                        ),
                    }
                    for case in args.microbench
                ],
                "calibration_cases": list(model.calibration_cases),
                "holdout_used_for_fit": False,
                "holdout_max_absolute_error_pct": holdout[
                    "calibrated_max_absolute_error_pct"
                ],
                "holdout_gate_pct": args.holdout_max_error_pct,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"K4_FPGA_FULLPR_COMPONENT_{'PASS' if passed else 'FAIL'} "
        f"holdout_max_error_pct="
        f"{float(holdout['calibrated_max_absolute_error_pct']):.3f}"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
