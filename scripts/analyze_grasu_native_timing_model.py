#!/usr/bin/env python3
"""Fit and validate the native GraSU/ReGraph measured timing envelope."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.calibration.grasu_native import (  # noqa: E402
    DEFAULT_MATRIX,
    DEFAULT_REPEAT_MANIFEST,
    DEFAULT_SIMULATION_DIR,
    fit_native_timing_model,
    load_native_timing_records,
    native_group_summary,
    native_prediction_rows,
    native_timing_model_to_dict,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--simulation-dir", type=Path, default=DEFAULT_SIMULATION_DIR)
    parser.add_argument("--repeat-manifest", type=Path, default=DEFAULT_REPEAT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    matrix_path = args.matrix.resolve()
    simulation_dir = args.simulation_dir.resolve()
    repeat_manifest = args.repeat_manifest.resolve()
    out_dir = args.out_dir.resolve()
    records = load_native_timing_records(matrix_path, simulation_dir, repeat_manifest)
    model = fit_native_timing_model(records)
    predictions = native_prediction_rows(model, records)
    summaries = native_group_summary(predictions)

    holdout_e2e = next(
        row
        for row in summaries
        if row["role"] == "holdout" and row["target"] == "event_e2e"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    model_payload = native_timing_model_to_dict(model)
    (out_dir / "model.json").write_text(
        json.dumps(model_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_csv(out_dir / "predictions.csv", predictions)
    write_csv(out_dir / "group_summary.csv", summaries)
    manifest = {
        "schema_version": 1,
        "status": "PASS",
        "claim_class": model.claim_class,
        "fit_role": "calibration_only",
        "holdout_used_for_fit": False,
        "matrix": str(matrix_path),
        "matrix_sha256": sha256(matrix_path),
        "simulation_dir": str(simulation_dir),
        "repeat_manifest": str(repeat_manifest),
        "repeat_manifest_sha256": sha256(repeat_manifest),
        "hardware_sample_counts": {
            record.case: record.hardware_samples for record in records
        },
        "calibration_cases": list(model.calibration_cases),
        "record_count": len(records),
        "holdout_event_e2e_median_absolute_error_pct": holdout_e2e[
            "calibrated_median_absolute_error_pct"
        ],
        "holdout_event_e2e_max_absolute_error_pct": holdout_e2e[
            "calibrated_max_absolute_error_pct"
        ],
        "acceptance": {
            "holdout_event_e2e_median_absolute_error_pct_max": 5.0,
            "holdout_event_e2e_max_absolute_error_pct_max": 10.0,
            "passed": holdout_e2e["calibrated_median_absolute_error_pct"] <= 5.0
            and holdout_e2e["calibrated_max_absolute_error_pct"] <= 10.0,
        },
        "limitations": list(model.limitations),
    }
    if not manifest["acceptance"]["passed"]:
        manifest["status"] = "FAIL"
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if manifest["status"] != "PASS":
        raise RuntimeError("native measured-envelope holdout gate failed")
    print(
        "PASS native timing envelope: "
        f"holdout_median={holdout_e2e['calibrated_median_absolute_error_pct']:.2f}% "
        f"holdout_max={holdout_e2e['calibrated_max_absolute_error_pct']:.2f}% "
        f"-> {out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
