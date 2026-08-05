#!/usr/bin/env python3
"""Fit the routed K4-shared ResPR envelope from realized work."""

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
    fit_k4_respr_component_model,
    k4_component_prediction_rows,
    k4_group_summary,
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
    parser.add_argument("--clock-mhz", type=float, default=150.0)
    parser.add_argument("--holdout-max-error-pct", type=float, default=20.0)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    records = load_k4_timing_records(
        args.summary, args.case, clock_mhz=args.clock_mhz
    )
    model = fit_k4_respr_component_model(records)
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
                "semantic": "vertices + total correction/propagation PMA slots; zero intercept",
                "limitations": [
                    "The target is a routed OpenCL event envelope, not an on-kernel counter.",
                    "The two coefficients are identified from two calibration topologies.",
                    "Transfer beyond one-partition insertion workloads requires "
                    "new holdout evidence.",
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
        f"K4_FPGA_RESPR_COMPONENT_{'PASS' if passed else 'FAIL'} "
        f"holdout_max_error_pct="
        f"{float(holdout['calibrated_max_absolute_error_pct']):.3f}"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
