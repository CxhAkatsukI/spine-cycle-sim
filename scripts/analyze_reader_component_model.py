#!/usr/bin/env python3
"""Fit and validate the Phase 5A structured reader component model.

Fits a non-negative reader component model on synthetic D-stage calibration
evidence (a pre-declared split — the calibration/holdout groups are fixed in
this file, not chosen after seeing results) and validates it on synthetic
holdout evidence plus the real / real-like Amazon slices.

Primary target: median_reader_ms. R stays a diagnostic sub-model of the D span
and is not added into the serial E2E total.

Usage:
    python3 scripts/analyze_reader_component_model.py --out-dir <DIR>
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.calibration import (  # noqa: E402
    fit_reader_component_model,
    load_reader_rows,
    reader_group_summary,
    reader_group_summary_field_order,
    reader_component_model_to_dict,
    reader_prediction_field_order,
    reader_prediction_row,
    write_json,
    write_rows_csv,
)
from spine_cycle_sim.calibration.maintenance import DEFAULT_FREQ_MHZ  # noqa: E402

# Pre-declared calibration / holdout split (fixed before fitting).
DEFAULT_CALIBRATION_DIRS = [
    "results/dstage_phase3a4_replay_calibration_hw_20260719_155924",
    "results/phase3c_full_partition_calibration_hw_20260719_175201",
    "results/phase3b_bottleneck_synthetic_hw_20260719_172739",
]
DEFAULT_HOLDOUT_SYNTHETIC_DIRS = [
    "results/phase3c_full_partition_holdout_hw_20260719_175623",
    "results/dstage_phase3a4_replay_holdout_hw_20260719_154734",
    "results/phase3c_final_validation_hw_20260719_175901",
]
DEFAULT_HOLDOUT_REAL_DIRS = [
    "results/phase4a_amazon_exact_slices_hw_20260719_224034",
    "results/phase3d_amazon_slices_hw_20260719_220659",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, default=ROOT)
    parser.add_argument("--calibration-dir", action="append", default=None)
    parser.add_argument("--holdout-synthetic-dir", action="append", default=None)
    parser.add_argument("--holdout-real-dir", action="append", default=None)
    parser.add_argument("--freq-mhz", type=float, default=DEFAULT_FREQ_MHZ)
    parser.add_argument(
        "--weight-mode",
        choices=["relative", "sqrt_relative", "none"],
        default="relative",
    )
    return parser.parse_args()


def _resolve(root: Path, paths: list[str]) -> list[Path]:
    resolved: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            path = root / path
        resolved.append(path)
    return resolved


def _load_group(path: Path, role: str) -> list[tuple[dict, str, str]]:
    group = path.name
    return [(row, group, role) for row in load_reader_rows(path)]


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    root = args.evidence_root

    calibration_dirs = _resolve(root, args.calibration_dir or DEFAULT_CALIBRATION_DIRS)
    holdout_synth_dirs = _resolve(root, args.holdout_synthetic_dir or DEFAULT_HOLDOUT_SYNTHETIC_DIRS)
    holdout_real_dirs = _resolve(root, args.holdout_real_dir or DEFAULT_HOLDOUT_REAL_DIRS)

    calibration_rows: list[dict] = []
    labeled: list[tuple[dict, str, str]] = []
    for path in calibration_dirs:
        loaded = _load_group(path, "calibration")
        calibration_rows.extend(row for row, _, _ in loaded)
        labeled.extend(loaded)
    for path in holdout_synth_dirs:
        labeled.extend(_load_group(path, "holdout_synthetic"))
    for path in holdout_real_dirs:
        labeled.extend(_load_group(path, "holdout_real"))

    model = fit_reader_component_model(
        calibration_rows, freq_mhz=args.freq_mhz, weight_mode=args.weight_mode
    )

    predictions = []
    for row, group, role in labeled:
        prediction = model.predict(row, group=group, role=role, freq_mhz=args.freq_mhz)
        if prediction is not None:
            predictions.append(prediction)
    predictions.sort(key=lambda p: (p["role"], p["group"], p["reader_actual_cycles"]))

    rows = [reader_prediction_row(p) for p in predictions]
    summaries = reader_group_summary(predictions)

    model_json = reader_component_model_to_dict(model)
    model_json["evidence"] = {
        "calibration_dirs": [str(p) for p in calibration_dirs],
        "holdout_synthetic_dirs": [str(p) for p in holdout_synth_dirs],
        "holdout_real_dirs": [str(p) for p in holdout_real_dirs],
    }
    model_json["prediction_count"] = len(predictions)

    write_json(args.out_dir / "reader_model.json", model_json)
    write_rows_csv(args.out_dir / "reader_predictions.csv", rows, reader_prediction_field_order())
    write_rows_csv(
        args.out_dir / "reader_group_summary.csv", summaries, reader_group_summary_field_order()
    )

    coefs = {k: round(v, 3) for k, v in model.coefficients.items()}
    print(f"predictions={len(predictions)} coefficients={coefs}")
    print(f"wrote {args.out_dir / 'reader_model.json'}")
    print(f"wrote {args.out_dir / 'reader_predictions.csv'}")
    print(f"wrote {args.out_dir / 'reader_group_summary.csv'}")
    print()
    print("group_summary:")
    header = reader_group_summary_field_order()
    print("  " + "  ".join(header))
    for summary in summaries:
        print("  " + "  ".join(_fmt(summary[key]) for key in header))
    return 0


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
